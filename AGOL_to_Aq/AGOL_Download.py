# AGOL_Download.py
# Nick Youngstrom

# This function accesses an ArcGIS Online web service and creates a local copy of all features in the service.
# Secure services can be used if you have priveleges to access them

# Syntax:    AGOLDownload(user,password,portal,tokenURL,serviceURL,fields,outdata)
# Parameters:
# *All paremeters must be entered as text*
#     User - Your AGOL username
#     Pass - Your AGOL password
#     Refer - https://www.arcgis.com
#           -For DNRC, this URL is: https://mtdnrc.maps.arcgis.com
#     tokenURL - https://www.arcgis.com/sharing/rest/generateToken
#              -For DNRC services, this URL is https://mtdnrc.maps.arcgis.com/sharing/rest/generateToken
#     baseURL - the rest endpoint of the service you want to download
#             -To get this, go to the item details for the service, then copy the service URL
#     fields - If desired, specify which attribute fields to download
#            -To download all, enter *
#     outdata - The output location you want the file to save to
#
# Required python packages: arcpy, reguests, urllib.request, json



import arcpy
import os, sys
import urllib, requests, json
from arcgis.gis import GIS

arcpy.env.overwriteOutput = True

# AGOL Login Info
portal        = "https://mtdnrc.maps.arcgis.com"
user          = "CND367"
password      = "Goblin-King905"

# Item Details
tokenURL   = portal + "/sharing/rest/generateToken"
serviceURL = "https://services2.arcgis.com/DRQySz3VhPgOv7Bo/arcgis/rest/services/survey123_623adfe2a40544d88de2477a6c3c0791/FeatureServer"
outdata    = r"C:\Users\CND367\Documents\Aquarius_Alarm\Aquarius_Alarm\AGOL to Aq\download"


def AddError():
  e = sys.exc_info()
  print("Error: {}".format(e[1]))


def AGOLDownload(user,password,portal,tokenURL,serviceURL,fields,outdata):
  try:
    # Generate service token
    print("Generating service token...")
    payload  = {'username' : user,'password' : password,'referer' : portal,'f' : 'json' }
    r = requests.post(tokenURL, data=payload)
    data = json.loads(r.text)
    token = "token=" + data['token']
    print("Token acquired:\n" + token)
    try:
      # Get record extract limit
      urlstring = serviceURL + "?" + token + "&f=json"
      j = urllib.request.urlopen(urlstring)
      str_response = j.read().decode('utf-8')
      js = json.loads(str_response)
      maxrc = int(js["maxRecordCount"])
      print ("Record extract limit: %s" % maxrc)
      try:
        # Get object IDs of features
        where = "1=1"
        urlstring = serviceURL + "/query?" + token + "&where={}&returnIdsOnly=true&f=json".format(where)
        j = urllib.request.urlopen(urlstring)
        str_response = j.read().decode('utf-8')
        js = json.loads(str_response)
        idfield = js["objectIdFieldName"]
        idlist = js["objectIds"]
        idlist.sort()
        numrec = len(idlist)
        print ("Number of target records: %s" % numrec)
        try:
          # Download features
          print ("Gathering records...")
          fs = dict()
          for i in range(0, numrec, maxrc):
            torec = i + (maxrc - 1)
            if torec > numrec:
              torec = numrec - 1
            fromid = idlist[i]
            toid = idlist[torec]
            where = "{} >= {} and {} <= {}".format(idfield, fromid, idfield, toid)
            print ("  {}".format(where))
            urlstring = serviceURL + "/query?" + token + "&where={}&returnGeometry=true&outFields={}&f=json".format(where,'*')
            fs[i] = arcpy.FeatureSet()
            fs[i].load(urlstring)
          print ("Saving features...")
          fslist = []
          for key,value in fs.items():
            fslist.append(value)
          arcpy.management.Merge(fslist, outdata)
        except:
          AddError()
      except:
        AddError()
    except:
      AddError()
  except:
    AddError()

# Download AGOL feature service
if __name__ == "__main__":
  AGOLDownload(user,password,portal,tokenURL,serviceURL,"*",outdata)
