import struct,sys,string,traceback,random
from binascii import *
from ctypes import create_string_buffer
from scapy.all import *
from Protocols.HTTP import *

class PayloadGenerator:
	pkts = []
	payload = None
	contents = []
	uricontents = []
	itered = []

	#def __init__(self, rule_contents, flow):
	def __init__(self, rule, snort_vars):
		self.rule = rule
		self.contents = self.rule.contents
		self.uricontents = self.rule.uricontents
		self.payload = None
		self.flow = rule.flow
		self.itered = []
		self.snort_vars = snort_vars
		self.flip = False
		self.notSupported = False

		#These are for crafting packets
		self.src = ""
		self.dst = ""
		self.home = ""
		self.ext  = ""

		if self.rule.rawsources == "any":
			self.src = "any"
		elif self.rule.rawsources.find("/") != -1:
			self.src = self.rule.rawsources.split("/")[0]
		elif self.rule.rawsources[1:] in self.snort_vars:
			self.src = self.snort_vars[self.rule.rawsources[1:]]
		else:
			self.src = self.rule.rawsources

		if self.rule.rawdestinations == "any":
			self.dst = "any"
		elif self.rule.rawdestinations.find("/") != -1:
			self.dst = self.rule.rawdestinations.split("/")[0]
		elif self.rule.rawdestinations[1:] in self.snort_vars:
			self.dst = self.snort_vars[self.rule.rawdestinations[1:]]
		else:
			self.dst = self.rule.rawdestinations


		if self.rule.rawsources[1:] == "HOME_NET":
			self.home = "src"
		elif self.rule.rawdestinations[1:] == "HOME_NET":
			self.home = "dst"
	
		self.sport	   = ""
		self.dport	   = ""
		self.proto	   = self.rule.proto
		self.protocol      = ""
		self.ip  	   = IP()
		self.handshake     = False
		self.packets       = []

		self.parseComm(self.rule.rawsrcports, self.rule.rawdesports)
		#self.build()

	def build(self):
		#Simple HTTP string based checks
		httpCheck = ["POST","GET","User-Agent","Host","Cookie"]

		if self.flow and self.flow.established:
			self.build_handshake()

		oldc = None
		itered = []

		for c in self.contents:
			if not oldc:
				c.ini = 0

				c.end = len(c.payload)
			else:
				if c.distance == 0:
					c.ini = oldc.end
				else:
					c.ini = oldc.end + 1
				#c.ini = oldc.end + 1
				#c.end = c.ini + len(c.content)
				c.end = c.ini + len(c.payload)


			if c.offset and not oldc:
				c.ini = c.ini + c.offset
				c.end = c.end + c.offset

			if c.offset and oldc:
				# Here we should check for conflicts
				if c.ini < c.offset:
					c.ini = c.offset
					#c.end = c.ini + len(c.content)
					c.end = c.ini + len(c.payload)

			if c.distance and oldc:
				if oldc.end + c.distance > c.ini:
					c.ini = oldc.end + c.distance
					#c.end = oldc.end + c.distance + len(c.content)
					c.end = oldc.end + c.distance + len(c.payload)

			# Checks
			if c.depth and c.end > c.depth:
				print "Error here depth!" 

			# Checks
			if c.within and c.end > oldc.end + c.within:
				print "Error here within!" 
				
			oldc = c
			itered.append(c)
			#print "-> Ini: " + str(c.ini) + " End: " + str(c.end)

		# buffer size
		max = 0
		for c in itered:
			if c.end > max:
				max = c.end

		# perform padding with ' 's (blank spaces)
		padding = ""
		for i in range(0,max):
			padding = padding + " "
		self.payload = create_string_buffer(max)
		struct.pack_into(str(max) + "s", self.payload, 0, padding)

		# write payloads
		for c in itered:
			fmt = str(c.end - c.ini) + "s"
			struct.pack_into(fmt, self.payload, c.ini, c.payload)

		self.itered = itered

		#ADDED - FOR HTTP SUPPORT
		h = None
		if self.sport == "80" or self.dport == "80":
			for check in httpCheck:
				if self.payload.raw.lower().find(check.lower()) != -1:
					h = HTTP()
					h.check(self.payload.raw)
					h.build()
					break
			if self.uricontents:
				if not h: h = HTTP()
				uri = ""
				for u in self.uricontents:
					uri = "%s%s" % (uri, str(u.uricontent))
				h.uri = uri
				h.build()
		if h:
			if self.payload.raw:
				h.payload = h.payload + self.payload.raw
			self.build_packet(h.payload)
			return h.payload
		else:
			self.build_packet(self.payload.raw)
			return self.payload

	def build_packet(self, payload):
		source_ip   = self.ip.src
		source_port = self.protocol.sport
		dest_ip	    = self.ip.dst
		dest_port   = self.protocol.dport
		flag        = "PA"

		if self.proto == "tcp":
			seq_num, ack_num = self.get_seqack()
			if seq_num is None:
				seq_num = random.randint(1024,(2**32)-1)
				ack_num = random.randint(1024,(2**32)-1)

			#This is the actual data packet that will be sent containing the payload
			p = IP(src=source_ip, dst=dest_ip)/TCP(flags=flag, sport=source_port, dport=dest_port, seq=seq_num, ack=ack_num)/payload

			#We need to ACK the packet
			returnAck = IP(src=dest_ip, dst=source_ip)/TCP(flags="A", sport=dest_port, dport=source_port, seq=p.ack, ack=(p.seq + len(p[Raw])))

			
			#Now we build the Finshake
			finAck = IP(src=source_ip, dst=dest_ip)/TCP(flags="FA", sport=source_port, dport=dest_port, seq=returnAck.ack, ack=returnAck.seq)
			finalAck = IP(src=dest_ip, dst=source_ip)/TCP(flags="A", sport=dest_port, dport=source_port, seq=finAck.ack, ack=finAck.seq+1)


			self.packets.append(p)
			self.packets.append(returnAck)
			self.packets.append(finAck)
			self.packets.append(finalAck)

			#Here we set the MSS to the size of the payload
			for packet in self.packets:
				if not TCP in packet or not Raw in p:
					continue

				mssLen = len(p[Raw])

				packet[TCP].options = []
				packet[TCP].options.append(('MSS', mssLen))

				packet[TCP].window = mssLen 

		elif self.proto == "udp":
			p = IP(src=source_ip, dst=dest_ip)/UDP(sport=source_port, dport=dest_port)/payload
	
			self.packets.append(p)

	def build_handshake(self):
		ipsrc   = self.ip.src
		ipdst   = self.ip.dst
		portsrc = self.protocol.sport
		portdst = self.protocol.dport
	
		#This is for to_client rules.  We need to change the source/dest
		if self.flow.to_client or self.flow.from_server:
			self.flip = True
			ipsrc = self.ip.dst
			ipdst = self.ip.src
			portsrc = self.protocol.dport
			portdst = self.protocol.sport
			
		client_isn = random.randint(1024, (2**32)-1)
		server_isn = random.randint(1024, (2**32)-1)

		syn = IP(src=ipsrc, dst=ipdst)/TCP(flags="S", sport=portsrc, dport=portdst, seq=client_isn)

		synack = IP(src=ipdst, dst=ipsrc)/TCP(flags="SA", sport=portdst, dport=portsrc, seq=server_isn, ack=syn.seq+1)

		ack = IP(src=ipsrc, dst=ipdst)/TCP(flags="A", sport=portsrc, dport=portdst, seq=syn.seq+1, ack=synack.seq+1)
	
		self.packets.append(syn)
		self.packets.append(synack)
		self.packets.append(ack)

	def get_seqack(self):
		if len(self.packets) == 0:
			return None,None

		if self.flip:
			seq = self.packets[-2].seq +1
			ack = self.packets[-2].ack
		else:
			seq = self.packets[-1].seq
			ack = self.packets[-1].ack

		return seq,ack

	def parseComm(self, sports, dports):
		if self.proto == "tcp":
			self.protocol = TCP()
		elif self.proto == "udp":
			self.protocol = UDP()
		else:
			print "Protocol Not Supported"
			self.notSupported = True
			return 1

		self.src = re.sub("\$",'',self.src)
		self.dst = re.sub("\$",'',self.dst)
		sports   = re.sub("\$",'',sports)
		dports   = re.sub("\$",'',dports)

		for var in self.snort_vars:
			m = re.search(var, self.src)
			if m:
				self.src = re.sub(var, self.snort_vars[var], self.src)
				break

		for var in self.snort_vars:
			m = re.search(var, self.dst)
			if m:
				self.dst = re.sub(var, self.snort_vars[var], self.dst)
				break

		if self.src.find("[") != -1:
			self.src = self.src.split(",")[0]
			self.src = re.sub("\[",'',self.src)
			self.src = re.sub("\]",'',self.src)
		
		if self.dst.find("[") != -1:
			self.dst = self.dst.split(",")[0]
			self.dst = re.sub("\[",'',self.dst)
			self.dst = re.sub("\]",'',self.dst)

		if self.src.find("!") != -1:
			if self.src.find(self.snort_vars["HOME_NET"]) != -1:
				self.src = self.snort_vars["EXTERNAL_NET"]
			elif self.src.find(self.snort_vars["EXTERNAL_NET"]) != -1:
				self.src = self.snort_vars["HOME_NET"]

		if self.dst.find("!") != -1:
			if self.dst.find(self.snort_vars["HOME_NET"]) != -1:
				self.dst = self.snort_vars["EXTERNAL_NET"]
			elif self.dst.find(self.snort_vars["EXTERNAL_NET"]) != -1:
				self.dst = self.snort_vars["HOME_NET"]
		#If the source is using CIDR notiation
		#Just pick the first IP in the subnet
		if self.src.find("/") != -1:
			self.src = self.src.split("/")[0]
			self.src = "%s.%s" % (self.src[:self.src.rfind(".")],"1")
		#Same for the dst
		if self.dst.find("/") != -1:
			self.dst = self.dst.split("/")[0]
			self.dst = "%s.%s" % (self.dst[:self.dst.rfind(".")],"1")
		#If any on either src or dst just use any IP
		if self.src == "any":
			self.src = "1.1.1.1"
		if self.dst == "any":
			self.dst = "2.2.2.2"

		try:
			self.ip.src = self.src
			self.ip.dst = self.dst
		except:
			print "ERROR:"
			print self.src
			print self.dst


		for var in self.snort_vars:
			m = re.search(var, sports)
			if m:
				sports = re.sub(var, self.snort_vars[var], sports)
				break

		for var in self.snort_vars:
			m = re.search(var, dports)
			if m:
				dports = re.sub(var, self.snort_vars[var], dports)
				break

		if sports == "any":
			self.sport = str(RandShort())
		else:
			self.sport = str(sports)

		if self.sport.find(":") != -1:
			self.sport = str(sports.split(":")[0])
		if self.sport.find("!") != -1:
			self.sport = str(int(self.sport[1:]) -1)
		if self.sport.find("[") != -1:
			self.sport = str(self.sport.split(",")[1])
			self.sport = re.sub("\[",'',self.sport)
			self.sport = re.sub("\]",'',self.sport)

		if dports == "any":
			self.dport = str(RandShort())
		else:
			self.dport = str(dports)

		if self.dport.find(":") != -1:
			self.dport = str(self.dport.split(":")[0])
		if self.dport.find("!") != -1:
			self.dport = str(int(self.dport[1:]) -1)
		if self.dport.find("[") != -1:
			self.dport = str(self.dport.split(",")[1])
			self.dport = re.sub("\[",'', self.dport)
			self.dport = re.sub("\]",'',self.dport)

		try:
			self.protocol.sport = int(self.sport)
			self.protocol.dport = int(self.dport)
		except:
			print "Error Assigning SPORT or DPORT"
			print "SPORT: %s" % str(self.sport)
			print "DPORT: %s" % str(self.dport)
			traceback.print_exc()
		

	def hexPrint(self):
		str = ''
		str = str + "-------- Hex Payload Start ----------\n"
		for i in range(0,len(self.payload)):
			str = str + " " + hexlify(self.payload[i])
			if i > 0 and (i + 1) % 4 == 0:
				str = str + " "
			if i > 0 and (i + 1) % 8 == 0:
				str = str + "\n"
		str = str + "\n--------- Hex Payload End -----------\n"
		return str

	def asciiPrint(self):
		str = ''
		str = str + "-------- Ascii Payload Start ----------\n"
		for i in range(0,len(self.payload)):
			c = self.payload.raw[i]
			if c in string.printable:
				str = str + c
			else:
				str = str + "\\x" + hexlify(c)
		str = str + "\n--------- Ascii Payload End -----------\n"
		return str
			
	def PrintOffsets(self):
		print " Start		End"		
		if self.itered == []:
			return
		for c in self.itered:
			print "%05s  %10s" % (str(c.ini), str(c.end))

	def __str__(self):
		if self.payload == None:
			print "No payload to print"
			return ""

		printable = 1
		for i in range(0,len(self.payload)):
			if not self.payload[i] in string.printable:
				printable = 0
		if printable:
			return self.asciiPrint()
		else:
		   return self.hexPrint()
