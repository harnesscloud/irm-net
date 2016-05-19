import json
import os

def load_web_resources():
   ret = { }
   
   try:   
	   path = os.path.dirname(os.path.abspath(__file__))
	   with open(path + '/webs.json') as data_file:    
		  data = json.load(data_file)
   except:
      return { }
	   
   try: 	  
	   for d in data:
		  name = "web-" + d.lower()
		  ret[name] = {"Type": "Web-" + d}
		  ret[name]["Attributes"] = {
		     "IP": data[d]["IP"]
		  }
	   return ret
   except:
      print "Invalid format: public.json!"
      return {}
               
   
    


