import json
import requests
import cherrypy
import time
import socket
import paho.mqtt.client as PahoMQTT
import sub.functionsDatabaseServer as fDb
from datetime import datetime
import mysql.connector
import re


class DatabaseServer(object):
	def __init__(self):
		file_content2=json.load(open('confFileDBServer.json'))
		self.catalogAddress=file_content2.get('ipCatalog')
		self.catalogPort=int(file_content2.get('catalogPort'))
		self.user=file_content2.get('dbServerUser')
		self.passwd=file_content2.get('dbServerPassword')
		self.port=int(file_content2.get('dbServerPort'))
		self.topic=file_content2.get('topic')
		self.deletionTime=int(file_content2.get('deletionTime'))
		s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("8.8.8.8", 80))
		self.address=s.getsockname()[0]


class DatabaseRest(object):
	exposed=True	
	def __init__(self,clientID):
		self.ID=clientID
		self.database=DatabaseServer()	
	def GET(self,*uri,**params):
		toReturn=False
		if len(uri)==0:
			#The server is ensuring that the database is really on that ip/port			
			toReturn="HI"
		elif len(uri)==1:
			#4 servers generating 3 different types of request 
			if uri[0]!='temperatures' and uri[0]!='positions' and uri[0]!='whereIAm':
				raise cherrypy.HTTPError(400, "ERROR: bad request")	
			else:
				#Temperature's request
				if uri[0]=='temperatures':
					if len(list(params.values()))!=1 or list(params.keys())[0]!='typeOfRequest':
						raise cherrypy.HTTPError(400, "ERROR: incorrect number of params")
					else:
						typeOfRequest=params["typeOfRequest"]
						#Asking data about the whole period
						if typeOfRequest=='all':
							valueToReturn=fDb.selectAll(self.database.user,self.database.passwd,"temperatures")
							toReturn=json.dumps({'value':valueToReturn})
						#Asking data just about yesterday
						elif typeOfRequest=='today':
							valueToReturn=fDb.selectLastDay(self.database.user,self.database.passwd,"temperatures")
							toReturn=json.dumps({'value':valueToReturn})
						else:
							raise cherrypy.HTTPError(400, "ERROR: bad params")								
				#Position's request
				elif uri[0]=='positions':
					if len(list(params.values()))!=1 or list(params.keys())[0]!='typeOfRequest':
						raise cherrypy.HTTPError(400, "ERROR: incorrect number of params")
					else:
						typeOfRequest=params["typeOfRequest"]
						if typeOfRequest=='all':
							valueToReturn=fDb.selectAll(self.database.user,self.database.passwd,"positions")
							toReturn=json.dumps({'value':valueToReturn})
						elif typeOfRequest=='today':
							valueToReturn=fDb.selectLastDay(self.database.user,self.database.passwd,"positions")
							toReturn=json.dumps({'value':valueToReturn})
						else:
							raise cherrypy.HTTPError(400, "ERROR: bad params")	
				else:	
					#Third case --> whereIAm request
					if len(list(params.values()))!=1 or list(params.keys())[0]!='macToSearch':
						raise cherrypy.HTTPError(400, "ERROR: error with the parameters")
					else:
						macToSearch=params["macToSearch"]
						try:
							pat = re.compile(r'(?:[0-9a-fA-F]:?){12}')
							test = pat.match(macToSearch)
							if test is None:
								print("MAC DO NOT FIT")
								valueToReturn=False
							else:
								valueToReturn=fDb.selectLastPosition(self.database.user,self.database.passwd,macToSearch)
						except Exception as e:
							print(e)
						if valueToReturn is None:
							valueToReturn=[]
						toReturn=json.dumps({'value':valueToReturn})
		else:
			raise cherrypy.HTTPError(400, "ERROR: too many params in the uri")	
		return toReturn

class subscriberServer(object):
	def __init__(self,databaseServer):
		self._paho_mqtt = PahoMQTT.Client('subscriberServer', False)
		self._paho_mqtt.on_connect = self.myOnConnect
		self._paho_mqtt.on_message = self.myOnMessageReceived
		self.ipBroker=""
		self.portBroker=""
		self.database=databaseServer

	def updateBroker(self, ipBroker,portBroker):
		self.ipBroker=ipBroker
		self.portBroker=portBroker
	def start(self):
		self._paho_mqtt.connect(self.ipBroker, int(portBroker))
		self._paho_mqtt.loop_start()
	def mySubscribe (self, topic):
		print ("subscribing to %s" % (topic))
		self._paho_mqtt.subscribe(topic, 2)
	def myOnConnect(self, paho_mqtt,userdata,flags,rc):
		print (f"Connected to {self.ipBroker} with result code: {rc}")
	def stop(self):
		self._paho_mqtt.loop_stop()
		self._paho_mqtt.disconnect()

	def myOnMessageReceived(self, paho_mqtt , userdata, msg):
		#A QUESTO PUNTO DOVREBBE AVVENIRE L'INSERIMENTO A DATABASE DEI DATI --> DOPO CONTROLLO FORMATO
		"""
		MODUS OPERANDI: 
		1) CAPIRE CHE TIPO DI INSERIMENTO SI VUOLE FARE
		2) CONTROLLO CHE I DATI IN INGRESSO SIANO COERENTI
		3) APERTURA CONNESSIONE AL DATABASE DESIDERATO
		4) INSERIMENTO 
		"""
		msgDict=json.loads(msg.payload)
		
		if msg.topic.split("/")[2]=="t" or msg.topic.split("/")[2]=="b":
			if msg.topic.split("/")[2]=="t":
				result=fDb.checkValidityPut(self.database.user,self.database.passwd,msgDict,"temperatures")
				if result==True:
					fDb.addData(self.database.user,self.database.passwd, msgDict, 'temperatures')
				else: 
					print("Error: problems with data!")
			elif msg.topic.split("/")[2]=="b":
				try:
					result=fDb.checkValidityPut(self.database.user,self.database.passwd,msgDict,"positions")
				except Exception as e:
					print("Not valid!")
					print(e)
				if result==True:
					fDb.addData(self.database.user,self.database.passwd, msgDict, 'positions')
				else: 
					print("Error: problems with data!")
		else:
			print("Error: unknown topic!")

if __name__=="__main__":
	#REST PART!
	dbServerClient=DatabaseRest('DatabaseServer')
	conf={
		'/':{
		'request.dispatch':cherrypy.dispatch.MethodDispatcher(),
		}
	}
	port=dbServerClient.database.port
	cherrypy.config.update({'server.socket_host': '0.0.0.0','server.socket_port': port})
	cherrypy.tree.mount(dbServerClient,'/',conf)
	cherrypy.engine.start()

	#MQTT PART!!!
	c=subscriberServer(dbServerClient.database)

	countException=0
	while True and countException<3:
		try:
			catalogAddress=dbServerClient.database.catalogAddress
			catalogPort=dbServerClient.database.catalogPort
			body={'whatPut':1,'IP':dbServerClient.database.address,'port':port, 'last_update':0, 'whoIAm':dbServerClient.ID, 'category':'database','field':''}
			r=requests.put('http://'+str(catalogAddress)+':'+str(catalogPort),json=body)
			newBroker=r.json()['ipBroker']
			portBroker=r.json()['portBroker']
			#Essentially controls to check the new information about the broker
			#Lost connection
			if c.ipBroker!="" and newBroker=="" or c.portBroker!="" and portBroker=="":
				print("Broker server disconnected")
				c.ipBroker=""
				c.portBroker=""
				c.stop()
			#Start the service	
			elif c.ipBroker=="" and newBroker!="" and c.portBroker=="" and portBroker!="":
				c.updateBroker(newBroker,portBroker)
				c.start()
				c.mySubscribe(dbServerClient.database.topic)
			#Updated info 
			elif c.ipBroker!=newBroker and newBroker!="" or c.portBroker!=portBroker and portBroker!="":
				c.stop()
				c.updateBroker(newBroker,portBroker)
				c.start()
				c.mySubscribe(dbServerClient.database.topic)
			#No info at disposition at the moment
			elif c.ipBroker=="" and newBroker=="" or c.portBroker=="" and portBroker=="":
				print("STILL NO BROKER!")
			actualTime=datetime.now()
			#Function called to remove operative data which are timed-out
			fDb.removeOutOfDate(dbServerClient.database.user,dbServerClient.database.passwd, actualTime,dbServerClient.database.deletionTime)
			timeSleep=r.json()['timeToSleep']
		except requests.exceptions.RequestException as e:
			countException+=1
			print(e)
			timeSleep=2
		time.sleep(timeSleep)
	cherrypy.engine.exit()
	c.stop()

