#! /usr/bin/env python
""" stic-text.py: Output a list of text for Calibre LVS.

    Copyright 2017 D. Mitch Bailey

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    requires python 2.7+ with python-gdsii, numpy
    pip install http://pypi.python.org/packages/source/p/python-gdsii/python-gdsii-0.2.1.tar.gz
    pip install numpy
"""

from __future__ import division

import sys
import getopt
import gzip
import re
import os
import copy
import xml.etree.ElementTree as ET
from gdsii.library import Library
from gdsii.elements import *
from gdsii.record import *
import numpy as np
from operator import attrgetter
from pprint import pprint
from ast import literal_eval

def OpenFile(theFileName, theMode="rt"):
    """Open a file (possibly compressed gz) and return file"""
    try:
        if theFileName.endswith(".gz"):
            myFile = gzip.open(theFileName, mode=theMode)
        else:
            myFile = open(theFileName, mode=theMode)
    except IOError as myErrorDetail:
        print("ERROR: Could not open " + theFileName + " " + str(myErrorDetail.args))
        raise IOError
    return myFile

def GetOrientation(theElement):
    """Return a combined reflection/rotation orientation.

    R0, R90, R180, R270, MX, MXR90, MY, MYR90
    Doesn't handle magnification.
    """
    if theElement.strans and (theElement.strans & int('1000000000000000', 2)):
        if not theElement.angle: return "MX"
        if theElement.angle == 90: return "MXR90"
        if theElement.angle == 180: return "MY"
        if theElement.angle == 270: return "MYR90" 
    else:
        if not theElement.angle: return "R0"
        if theElement.angle == 90: return "R90"
        if theElement.angle == 180: return "R180"
        if theElement.angle == 270: return "R270"
    print("ERROR: Invalid transform " + "{0:016b}".format(theElement.strans) + " in element")  
    raise ValueError

def GetTransform(theOrientation, theTranslation):
    """Return a transformation matrix for given orientation, translation.

    return: [(z0,y0,z0), (x1,y1,z1), (x2,y2,z2)] 
    """
    if theOrientation == "R0":
        myRotation = np.array([(1,0,0), (0,1,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "R90":
        myRotation = np.array([(0,1,0), (-1,0,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "R180":
        myRotation = np.array([(-1,0,0), (0,-1,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "R270":
        myRotation = np.array([(0,-1,0), (1,0,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "MX":
        myRotation = np.array([(1,0,0), (0,-1,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "MXR90":
        myRotation = np.array([(0,1,0), (1,0,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "MY":
        myRotation = np.array([(-1,0,0), (0,1,0), (0,0,1)], dtype=np.int64)
    if theOrientation == "MYR90":
        myRotation = np.array([(0,-1,0), (-1,0,0), (0,0,1)], dtype=np.int64)
    myTranslation = np.array([(1,0,0), (0,1,0), (theTranslation[0][0],theTranslation[0][1],1)],
                             dtype=np.int64)
#    myScale = np.array([(float(theScale),0.,0.),(0.,float(theScale),0.),(0.,0.,1.)], dtype=np.float64)
#    myTransform = np.dot(np.dot(myScale, myRotation), myTranslation)
    myTransform = np.dot(myRotation, myTranslation)
    return myTransform

##def FlipPort(theWinding, theOrientation):
##    """Return 'R' for clockwise, 'L' for counter-clockwise."""
##    if theOrientation.startswith("R"):
##        myNewWinding = theWinding
##    else:
##        myNewWinding = 'R' if theWinding == 'L' else 'L'
##    return myNewWinding
##
def Transform(thePointList, theTransform):
    """Returns a list of transformed points.

    return: [(x,y), ...]
    """
    myResult = []  # [(x,y), ...]
    for point_it in thePointList:
        myPoint = [point_it[0], point_it[1], 1]
        myProduct = np.dot(myPoint, theTransform)
        myResult.append((myProduct[0], myProduct[1]))
    return myResult

##def NormalizeBox(theBox):
##    """Normalize (LowerLeft, UpperRight) box coordinates.
##
##    return: [(left, bottom), (right, top)]
##    """
##    return [(min(theBox[0][0], theBox[1][0]), min(theBox[0][1], theBox[1][1])),
##            (max(theBox[0][0], theBox[1][0]), max(theBox[0][1], theBox[1][1]))]
##
##def GetLayerType(thePort):
##    """Return "layerNumber-dataType". """
##    return thePort.find('layerNumber').text + "-" + thePort.find('dataType').text
##
def GetTextType(thePortText):
    """Return ("inputTextLayerNumber textType", "outputTextLayerNumber textType"). """
    myInputLayerPair = thePortText.find('inputLayer')
    myInputLayer = myInputLayerPair.find('layerNumber').text \
                   + " " + myInputLayerPair.find('textType').text
    myOutputLayerPair = thePortText.find('outputLayer')
    if myOutputLayerPair is None:
        myOutputLayer = myInputLayer
    else:
        myOutputLayer = myOutputLayerPair.find('layerNumber').text \
                        + " " + myOutputLayerPair.find('textType').text
    return (myInputLayer, myOutputLayer)

def PrintParameters(theStackedChip):
    """Print XML parameters."""
    print("Top CDL " + theStackedChip.find('topCdlFile').text
          + ", Top SUBCKT " + theStackedChip.find('topCell').text)
##    print("User units " + theStackedChip.find('userUnits').text)
##    print("Tolerance: " + theStackedChip.find('tolerance').text)
    chipCount = 0
    for chip_it in theStackedChip.findall('chip'):
        chipCount += 1
        print("\nChip " + str(chipCount) + ":")
        print(" CDL instance: " + chip_it.find('instanceName').text)
        if chip_it.find('subcktName') is not None:
            mySubcktName = chip_it.find('subcktName').text
        else:
            mySubcktName = "look up in CDL"
        print(" CDL file: " + chip_it.find('cdlFileName').text
              + ", top block: " + mySubcktName)
        print(" GDS file: " + chip_it.find('gdsFileName').text
              + ", top block: " + chip_it.find('layoutName').text)
        print(" Orientation: " + chip_it.find('orientation').text
              + "; Offset: (" + chip_it.find('offset').find('x').text
              + ", " + chip_it.find('offset').find('y').text + ")"
              + "; Shrink: " + chip_it.find('shrink').text)
        for port_it in chip_it.findall('portText'):
            (myPortText, myOutputText) = GetTextType(port_it)
            print(" Port text input: " + myPortText + "; output: " + myOutputText)
            
def ReadTopCdlFile(theStackedChip):
    """Read a CDL netlist and return a list of top instances with nets.

    returns {instanceName: {'master': masterName, 'nets': portList}, ...}, set(connectedNet, ...)
    """
    myTopCell = theStackedChip.find('topCell').text
    myTopCdlFile = theStackedChip.find('topCdlFile').text
    mySubcktStartRE = re.compile("^\.[sS][uU][bB][cC][kK][tT]\s+(\S+)")
    print("Reading " + myTopCdlFile)
    myCdlFile = OpenFile(myTopCdlFile)
    mySaveInstances = False
    myLine = ""
    myInstances = {}  # {instanceName: {'master': masterName, 'nets': portList}, ...}
    myUsedNets = set()
    myNetConnections = set()
    for line_it in myCdlFile:
        if line_it.startswith("*"): continue  #ignore comments
        if not line_it.strip(): continue  #ignore blank lines
        if line_it.startswith("+"):
            myLine += " " + line_it[1:]  # remove leading '+'
        else:
            if myLine:
                if myLine.startswith("."):
                    myMatch = mySubcktStartRE.search(myLine)
                    if myMatch and myMatch.group(1) == myTopCell:
                        mySaveInstances = True
                    else:
                        mySaveInstances = False
                if mySaveInstances and myLine.startswith("X"):
                    myWordList = myLine.split()
                    myInstances[myWordList[0]] = {'master': myWordList[-1],
                                                  'nets': myWordList[1:-1]}
                    myInstanceNets = set()
                    for net_it in myWordList[1:-1]:  # unique nets used in this instance
                        if net_it not in myInstanceNets and net_it != "/":
                            myInstanceNets.add(net_it)
                    for net_it in myInstanceNets:
                        if net_it in myUsedNets:  # 2 or more connections
                            myNetConnections.add(net_it)
                        else:  # first connections
                            myUsedNets.add(net_it)
                elif not mySaveInstances and myInstances:  # finished top cell
                    break
            myLine = line_it
    if not myInstances:
        print("ERROR: Could not find subckt " + myTopCell + " in " + myTopCdlFile)
        raise NameError
    return myInstances, myNetConnections

##def BoxContains(theBox, thePoint):
##    """True if theBox (2 tuple list) contains thePoint (tuple)."""
##    return True if (theBox[0][0] <= thePoint[0] and theBox[1][0] >= thePoint[0]
##                    and theBox[0][1] <= thePoint[1] and theBox[1][1] >= thePoint[1]) else False
##
def MapCdlPorts(theTopCell, theCdlFile, theParentNetList):
    """Return a dict of theTopCell ports mapped to parent nets.

    return: {portName: topNet, ...}
    """
    mySubcktStartRE = re.compile("^\.[sS][uU][bB][cC][kK][tT]\s+(\S+)")
    print("\nReading " + theCdlFile)
    myCdlFile = OpenFile(theCdlFile)
    mySaveInstances = False
    myLine = ""
    myNetMap = {}  # {portName: topNet, ...}
    for line_it in myCdlFile:
        if line_it.startswith("*"): continue  #ignore comments
        if not line_it.strip(): continue  #ignore blank lines
        if line_it.startswith("+"):
            myLine += " " + line_it[1:]  # concatenate after removing leading '+'
        else:
            if myLine and myLine.startswith("."):
                myMatch = mySubcktStartRE.search(myLine)
                if myMatch and myMatch.group(1) == theTopCell:
                    myIndex = 0
                    for net_it in myLine.split()[2:]:
                        myNetMap[net_it] = theParentNetList[myIndex]
                        myIndex += 1
                    return myNetMap
            myLine = line_it
    print("ERROR: could not find " + theTopCell + " in " + theCdlFile)
    raise NameError

def CreateStructureIndex(theGdsiiLib):
    """Return a dict of structure indices.

    return: {structureName: structureObject, ...}
    """
    myStructureIndex = {}  # {structureName: structureObject, ...}
    for structure_it in theGdsiiLib:
        structure_it.processed = False
        myStructureIndex[structure_it.name.decode('utf-8')] = structure_it
    return myStructureIndex

##def GetBox(thePointList):
##    """"Return the bounding box of the point list."""
##    myMinX = thePointList[0][0]
##    myMaxX = myMinX
##    myMinY = thePointList[0][1]
##    myMaxY = myMinY
##    for xy_it in thePointList[1:]:
##        if myMinX > xy_it[0]:
##            myMinX = xy_it[0]
##        elif myMaxX < xy_it[0]:
##            myMaxX = xy_it[0]
##        if myMinY > xy_it[1]:
##            myMinY = xy_it[1]
##        elif myMaxY < xy_it[1]:
##            myMaxY = xy_it[1]
##    return([(myMinX, myMinY), (myMaxX, myMaxY)])
##
##def PromoteCellPorts(thePortLayers, thePortCellList, thePortType, theStructureIndex, theTopLayout, 
##                     theOrientation="R0", theTranslation=[(0,0)]):
##    """Promote low level cell ports to top level.
##
##    return: [{'type': portType, 'xy': pointList[1], 'box': pointList[2], 'winding': R|L,
##              'textLayer': layer-type}, ...]
##    errors: portLayers not in portCells, non-rectangular ports, non-boundary type ports
##    """
##    if not theTopLayout in theStructureIndex:
##        print("ERROR: Could not find " + theTopLayout + " in GDS file.")
##        raise NameError
##    myStructure = theStructureIndex[theTopLayout]
##    if not myStructure.processed:  # Do port checks for each structure only once.
##        myStructure.ports = []
##        for element_it in myStructure:
##            if element_it.__class__.__name__ == 'SRef':
##                myStructure.ports += PromoteCellPorts(thePortLayers, thePortCellList,
##                                                      thePortType, theStructureIndex,
##                                                      element_it.struct_name.decode('utf-8'),
##                                                      GetOrientation(element_it), element_it.xy)
##            elif element_it.__class__.__name__ == 'ARef':
##                myXStep = (element_it.xy[1][0] - element_it.xy[0][0]) / element_it.cols
##                myYStep = (element_it.xy[2][1] - element_it.xy[0][1]) / element_it.rows
##                myY = element_it.xy[0][1]
##                myOrientation = GetOrientation(element_it)
##                myChildName = element_it.struct_name.decode('utf-8')
##                for row_it in range(element_it.rows):
##                    myX = element_it.xy[0][0]
##                    for column_it in range(element_it.cols):
##                        myStructure.ports += PromoteCellPorts(thePortLayers, thePortCellList,
##                                                              thePortType, theStructureIndex,
##                                                              myChildName,
##                                                              myOrientation, [(myX, myY)])
##                        myX += myXStep
##                    myY += myYStep
##            elif element_it.__class__.__name__ == 'Boundary':
##                myLayerType = str(element_it.layer) + "-" + str(element_it.data_type)
##                if myLayerType in thePortLayers:
##                    if theTopLayout not in thePortCellList[myLayerType]:
##                        print("Warning: Layer " + myLayerType + " in unexpected cell " 
##                              + theTopLayout + " ignored.")
##                    else:
##                        myBox = GetBox(element_it.xy)
##                        myStructure.ports.append(
##                            {'type': thePortType[theTopLayout]['type'],
##                             'xy': [(0,0)], 'box': myBox, 'winding': 'R',
##                             'textLayer': thePortType[theTopLayout]['textLayer']})
##            elif hasattr(element_it, 'layer') and hasattr(element_it, 'data_type'):
##                myLayerType = str(element_it.layer) + "-" + str(element_it.data_type)
##                if myLayerType in thePortLayers:
##                    print("Warning: Layer-datatype " + myLayerType + " in unexpected element type "
##                          + element_it.__class__.__name__ + ".")
##        myStructure.processed = True
##    myPorts = []
##    if myStructure.ports:
##        myTransform = GetTransform(theOrientation, theTranslation)
##        for port_it in myStructure.ports:
##            myPorts.append({'type': port_it['type'], 'xy': Transform(port_it['xy'], myTransform),
##                            'box': NormalizeBox(Transform(port_it['box'], myTransform)),
##                            'winding': FlipPort(port_it['winding'], theOrientation),
##                            'textLayer': port_it['textLayer']})
##    return myPorts
##        
##def LoadGdsPorts(theChip, theStructureIndex, theTopLayout):
##    """Return a list of ports from GDS library.
##
##    return: [{'type': portType, 'xy': pointList[1], 'box': pointList[2],
##              'textLayer': layer-type}, ...]
##    """
##    myPortLayers = set()
##    myPortCellList = {}  # {layer-type: [cell1, cell2, ...], ...}
##    myPortType = {}  # {cell: {'type': type, 'textLayer': layer-type}, ...}
##    for port_it in theChip.findall('port'):
##        myLayerType = GetLayerType(port_it)
##        if myLayerType not in myPortLayers:
##            myPortLayers.add(myLayerType)
##            myPortCellList[myLayerType] = []
##        for portCell_it in port_it.findall('portCell'):
##            myPortCellList[myLayerType].append(portCell_it.text)
##            if portCell_it.text in myPortType:
##                print("ERROR: cell " + portCell_it.text + " is defined as both "
##                      + myPortType[portCell_it.text] + " and " + port_it.find('type').text)
##            else:
##                myPortText = GetTextType(port_it)
##                myPortType[portCell_it.text] = {'type': port_it.find('type').text,
##                                                'textLayer': GetTextType(port_it)}
##    myPortList = PromoteCellPorts(myPortLayers, myPortCellList, myPortType, 
##                                  theStructureIndex, theTopLayout)
##    return myPortList 
##
def LoadGdsText(theChip, theTopStructure):
    """Return a list of text on the top structure.

    return: [{'text': port, 'layer': layer type, 'xy': point}, ...]
    """
    myTextLayers = {}  # {layer type: outputLayerType, ...}
    for port_it in theChip.findall('portText'):
        (myPortText, myOutputText) = GetTextType(port_it)
        if myPortText != "no text":
            if myPortText not in myTextLayers:
                myTextLayers[myPortText] = myOutputText
            else:
                print("ERROR: Duplicate text definition in " + theChip.find('instanceName').text
                      + " " + myPortText + " -> " + myTextLayers[myPortText]
                      + " and " + myOutputText)
                raise ValueError
    myTextList = []  # [{'text': text, 'layer': layer type, 'xy': [(x, y)]}, ...]
    for element_it in theTopStructure:
        if element_it.__class__.__name__ == 'Text':
            myLayerType = str(element_it.layer) + " " + str(element_it.text_type)
            if myLayerType in myTextLayers:
                myTextList.append({'text': element_it.string.decode('utf-8'),
                                   'layer': myTextLayers[myLayerType],
                                   'xy': element_it.xy})
    return myTextList

def UserScale(thePoint, theScale):
    """Returns thePoint scaled to used coordinates"""
    myX = thePoint[0][0] / theScale
    myY = thePoint[0][1] / theScale
    return("{0:.12g} {1:.12g}".format(myX, myY))

##def AssignPorts(thePortList, theTextList, theTopLayout, theDbuPerUU):
##    """Return a list of text with port type centered at port origin.
##
##    return: [{'text': port, 'type': portType, 'xy': portCenter, 'winding': R|L}, ...]
##    errors: text mapped to multiple ports, text not mapped to any port.
##    """
##    myNamedPortList = []  # [{'text': port, 'type': portType, 'xy': [(x, y)], 'winding': R|L}, ...]
##    myUnmapCount = 0
##    print("Mapping " + str(len(theTextList)) + " texts to " + str(len(thePortList)) + " ports")
##    for text_it in theTextList:
##        myTextFound = False
##        for port_it in thePortList:
##            if BoxContains(port_it['box'], text_it['xy'][0]):
##                if myTextFound and myXY != port_it['xy']:
##                    print("Warning: Text in multiple ports: " + text_it['text']
##                          + " at " + UserScale(myXY, theDbuPerUU) + " and "
##                          + UserScale(text_it['xy'], theDbuPerUU) + " in " + theTopLayout)
##                    myUnmapCount += 1
##                elif text_it['layer'] != port_it['textLayer']:
##                    print("Warning: " + text_it['text']
##                          + " at " + UserScale(port_it['xy'], theDbuPerUU)
##                          + " on layer " + text_it['layer'] + " does not match expected " 
##                          + port_it['textLayer'] + " for port " + port_it['type'])
##                    myUnmapCount += 1
##                else:                    
##                    myNamedPortList.append({'text': text_it['text'],
##                                            'type': port_it['type'],
##                                            'xy': port_it['xy'],
##                                            'winding': port_it['winding']})
##                    port_it['assigned'] = True
##                    myTextFound = True
##                    myXY = port_it['xy']
##        if not myTextFound:
##            myUnmapCount += 1
##    myBlankPortCount = 0
##    for port_it in thePortList:
##        if not 'assigned' in port_it:  # Check blank ports.
##            if port_it['textLayer'] == "no text":
##                myNamedPortList.append({'text': "",
##                                        'type': port_it['type'],
##                                        'xy': port_it['xy'],
##                                        'winding': port_it['winding']})
##            else:
##                print("Warning: Port type " + port_it['type']
##                      + " at " + UserScale(port_it['xy'], theDbuPerUU)
##                      + " is missing text")
##                myBlankPortCount += 1
##    print(str(myUnmapCount) + " text ignored. " + str(myBlankPortCount) + " ports without text.")
##    return myNamedPortList
##
def TranslateChipPorts(thePortList, theOrientation, theTranslation, theScale):
    """Return a list of ports and transformed to final position in user units.
    return: [{'text': portName, 'xy': position}, ...]
    """
    myInstancePortList = []
    # [{'text': port, 'xy': "(x, y)"}, ...]
    myTransform = GetTransform(theOrientation, theTranslation)
    for port_it in thePortList:
        myInstancePortList.append({'text': port_it['text'],
                                   'layer': port_it['layer'],
                                   'xy': UserScale(Transform(port_it['xy'], myTransform),
                                                   theScale)})
    return myInstancePortList

def GetGdsPortData(theChip):
    """Translate GDS port data to final positions.

    return: [{'text': port, 'xy': "(x, y)"}, ...]
    Note: x, y in user units.
    """
    myLayoutName = theChip.find('layoutName').text
    myGdsFileName = theChip.find('gdsFileName').text
    myOrientation = theChip.find('orientation').text
    myShrink = float(theChip.find('shrink').text)
    print("Reading " + myGdsFileName)
    myGdsFile = OpenFile(myGdsFileName, "rb")
    myGdsiiLib = Library.load(myGdsFile)
    myInternalDbuPerUU = 1 / myGdsiiLib.logical_unit
    myOffset = theChip.find('offset')
    myX = float(myOffset.find('x').text) * myInternalDbuPerUU
    myY = float(myOffset.find('y').text) * myInternalDbuPerUU
##    if theUserUnits == 'um':
##        myOutputDbuPerUU = 1e-6 / myGdsiiLib.physical_unit
##    elif theUserUnits == 'nm':
##        myOutputDbuPerUU = 1e-9 / myGdsiiLib.physical_unit
##    else:
##        raise ValueError
    myStructureIndex = CreateStructureIndex(myGdsiiLib)
    print("Loading ports...")
#    myPortList = LoadGdsPorts(theChip, myStructureIndex, myLayoutName)
    if myLayoutName not in myStructureIndex:
        print("ERROR: Could not find " + myLayoutName + " in " + myGdsFileName)
        raise NameError
    myTextList = LoadGdsText(theChip, myStructureIndex[myLayoutName])
    print("Assigning text...")
#    myNamedPortList = AssignPorts(myPortList, myTextList, myLayoutName, myInternalDbuPerUU)
    return TranslateChipPorts(myTextList, myOrientation, [(myX, myY)],
                              myInternalDbuPerUU / myShrink)

def PrintChipPorts(theChip, theInstances, theNetConnections, theOutputFile):
    """Print individual chip text at top level."""
    myInstanceName = theChip.find('instanceName').text
    myCdlFile = theChip.find('cdlFileName').text
    if theChip.find('subcktName') is None:
        myMasterSubckt = theInstances[myInstanceName]['master']
    else:
        myMasterSubckt = theChip.find('subcktName').text
    myCdlPortMap = MapCdlPorts(myMasterSubckt, myCdlFile, theInstances[myInstanceName]['nets'])
    myGdsPortData = GetGdsPortData(theChip)
    myPrintedPorts = set()  # {localNet, ...}
##    for net_it in myCdlPortMap:  # Added entry to handle connected CDL nets without ports
##        myKey = (myInstanceName, "", myCdlPortMap[net_it])
##        myMappedPorts[myKey] = net_it
    for port_it in myGdsPortData:
        if port_it['text'] in myCdlPortMap:
##            myKey = (myInstanceName, port_it['xy'], myCdlPortMap[port_it['text']])
##            myMappedPorts[myKey] = port_it['text']
            theOutputFile.write(" ".join(("LAYOUT TEXT",
                                          "\"" + myCdlPortMap[port_it['text']] + "\"",
                                          port_it['xy'], port_it['layer'], "\n")))
            myPrintedPorts.add(port_it['text'])     
        else:
            print("ERROR: layout port " + port_it['text']
                  + " at (" + port_it['xy'] + ") of " + theChip.find('layoutName').text
                  + " in " + theChip.find('gdsFileName').text
                  + " not in subckt " + myMasterSubckt + " of " + myCdlFile)
    for net_it in myCdlPortMap:  # Check for CDL nets missing ports
        if net_it not in myPrintedPorts:
            print("WARNING: port " + net_it + " of " + myInstance + " has no layout text")
#    return myMappedPorts

##def CreateSortKey(theValue):
##    """Return a key for sorting with indices in numerical order and xy numerically ascending.
##
##    Offset the coordinates by 100,000uu so that alphabetical sort = numerical sort.
##    Eg. without offset (-40, 0), (-10, 0) -> (-00010, 00000), (-00040, 00000)
##    with 10000 offset (-40, 0), (-10, 0) -> (09960, 10000), (09990, 10000)
##    """
##    (myText, myType, myXY) = theValue
##    if myXY != "":
##        (myX, myY) = literal_eval(myXY)
##    else:
##        (myX, myY) = (2e6, 2e6)  # default coordinate key for netlist only text
##    if myText.endswith("]"):
##        myMatch = re.match(r"(.*)\[([0-9]*)\]$", myText)
##        if myMatch:
##            return("{0:s}[{1:010d}] {2:+020.5f} {3:+020.5f}".format(
##                myMatch.group(1), int(myMatch.group(2)), 1e6+float(myX), 1e6+float(myY)))
##    elif myText.endswith(">"):
##        myMatch = re.match("(.*)<([0-9]*)>$", myText)
##        if myMatch:
##            return("{0:s}<{1:010d}> {2:+020.5f} {3:+020.5f}".format(
##                myMatch.group(1), int(myMatch.group(2)), 1e6+float(myX), 1e6+float(myY)))
##    elif myText.endswith(")"):
##        myMatch = re.match(r"(.*)\(([0-9]*)\)$", myText)
##        if myMatch:
##            return("{0:s}({1:010d}) {2:+020.5f} {3:+020.5f}".format(
##                myMatch.group(1), int(myMatch.group(2)), 1e6+float(myX), 1e6+float(myY)))
##    elif myText.endswith("}"):
##        myMatch = re.match(r"(.*)\{([0-9]*)\}$", myText)
##        if myMatch:
##            return("{0:s}{{{1:010d}}} {2:+020.5f} {3:+020.5f}".format(
##                myMatch.group(1), int(myMatch.group(2)), 1e6+float(myX), 1e6+float(myY)))
##    return("{0:s} {1:+020.5f} {2:+020.5f}".format(myText, 1e6+float(myX), 1e6+float(myY)))
##
##def CreateSearchList(theXY, theTolerance):
##    """Return a list of coordinates for 2x2 array of points rounded to tolerance.
##
##    return ["(x, y)", "(x, y+t)", "(x+t, y)", "(x+t, y+t)"] or ["(x, y)"]
##    """
##    if theTolerance > 0.000001:  # ignore tolerance less than 1e-6 user units
##        (myX, myY) = literal_eval(theXY)
##        myRoundedX = round(myX / theTolerance) * theTolerance
##        myRoundedY = round(myY / theTolerance) * theTolerance
##        myKeyList = []  # ["(x, y)", ...]
##        for x_offset in range(0, 2):
##            for y_offset in range(0, 2):
##                myKeyList.append(
##                    "({0:.12g}, {1:.12g})".format(myRoundedX + theTolerance * x_offset,
##                                                  myRoundedY + theTolerance * y_offset))
##    else:
##        myKeyList = [theXY]
##    return myKeyList
##
##def CreateXyList(thePortIndex, theSortedPorts, theTolerance):
##    """Return a list of actual point coordinates with the tolerance of first point.
##
##    return ["(x, y)", ...]
##    """
##    (myText, myType, myXY) = theSortedPorts[thePortIndex]
##    myXyList = [myXY]
##    (myX, myY) = literal_eval(myXY)
##    for nextPort_it in range(thePortIndex+1, len(theSortedPorts)):
##        # Get XY of ports within tolerance
##        (myNextText, myNextType, myNextXY) = theSortedPorts[nextPort_it]
##        if not (myNextText == myText and myNextType == myType): break
##        (myNextX, myNextY) = literal_eval(myNextXY)
##        if round(abs(myNextX - myX) / theTolerance * 100000) > 100000: break
##        if round(abs(myNextY - myY) / theTolerance * 100000) <= 100000:
##            myXyList.append(myNextXY)
##    return myXyList
##
##def CreatePortLists(thePortData, theTolerance):
##    """Create a list of unique named ports and lists of blank ports at tolerance.
##
##    Returns: (set((text, type, xy), ...), {(type, roundedXY): set(xy, ...)})
##    """
##    myFinalPorts = set()  # ((text, type, "(x, y)"), ...)
##    myBlankPorts = {}  # {(type, "(x, y)"): set("(x, y)", ...), ...}
##    for portKey_it in thePortData:  # Create top level port list.
##        (myInstance, myXY, myType, myText) = portKey_it
##        if myText == "":
##            myKeyList = CreateSearchList(myXY, theTolerance)
##            for key_it in myKeyList:
##                myKey = (myType, key_it)
##                if myKey not in myBlankPorts:
##                    myBlankPorts[myKey] = set()
##                myBlankPorts[myKey].add(myXY)
##        else:
##            myFinalPorts.add((myText, myType, myXY))
##    return((sorted(myFinalPorts, key=CreateSortKey), myBlankPorts))
##
##def WithinTolerance(theFirstXY, theSecondXY, theTolerance):
##    """True if the x and y coordinates of 2 points are within the tolerance."""
##    (myFirstX, myFirstY) = literal_eval(theFirstXY)
##    (mySecondX, mySecondY) = literal_eval(theSecondXY)
##    if round(abs(myFirstX - mySecondX) / theTolerance * 100000) > 100000: return False
##    if round(abs(myFirstY - mySecondY) / theTolerance * 100000) > 100000: return False
##    return True
##
##def HasBlankPort(theInstance, theType, theXY, theTolerance, theBlankPorts, thePortData):
##    """True if there is a blank port on instance within tolerance."""
##    myKeyList = CreateSearchList(theXY, theTolerance)
##    myPortFound = False
##    for key_it in myKeyList:
##        myBlankKey = (theType, key_it)
##        if myBlankKey in theBlankPorts:
##            for blankXY_it in theBlankPorts[myBlankKey]:
##                if WithinTolerance(theXY, blankXY_it, theTolerance):     
##                    myPortKey = (theInstance, blankXY_it, theType, "")
##                    if myPortKey in thePortData:
##                        return True
##    return False
##
##def MultiplePorts(thePortIndex, theSortedPorts, thePrintedPorts):
##    """True if there are multiple ports for the text."""
##    (myText, myType, myXY) = theSortedPorts[thePortIndex]
##    for nextPort_it in range(thePortIndex + 1, len(theSortedPorts)):  # Check for duplicate ports
##        (myNextText, myNextType, myNextXY) = theSortedPorts[nextPort_it]
##        if myNextText != myText: break  # different text
##        if (myNextText, myNextXY) in thePrintedPorts: continue  # Already printed (same port)
##        if myNextXY == "": continue  # dummy port
##        if myText == myNextText:  # Coil text must be unique (look ahead)
##            return True
##    return False
##
##def GetSlicePort(theInstance, theXyList, theType, theText, thePortData):
##    """Returns (portName, winding) of slice if found."""
##    for xy_it in theXyList:
##        myKey = (theInstance, xy_it, theType, theText)
##        if myKey in thePortData:
##            return thePortData[myKey]
##    return False   
##
##def PrintReportHeader(theOutputFile, theSortedInstances, theInstances):
##    """Print report file heading."""
##    myOutput = "Check,Port,Type,X,Y"
##    for key_it in theSortedInstances:
##        myOutput += "," + key_it + "(" + theInstances[key_it]['master'] + ")"
##    theOutputFile.write(myOutput + "\n")
##    
##def CheckPortData(thePortData, theInstanceOrder, theInstances, theTolerance,
##                  theOutputFile, theNetConnections):
##    """Check the promoted ports' alignment and winding."""
##    (mySortedPorts, myBlankPorts) = CreatePortLists(thePortData, theTolerance)
##    myPrintedPorts = set()
##    myUsedCoils = set()
##    myLastText = ""
##    for port_it in range(len(mySortedPorts)):
##        (myText, myType, myXY) = mySortedPorts[port_it]
##        myPortOk = "O"
##        if (myText, myXY) in myPrintedPorts: continue
##        if myXY == "":
##            if myText == myLastText or myText not in theNetConnections: continue
##            # CDL net without layout port
##            myPortOk = "X"
##            myOutput = myText + ",,"
##            myXyList = [""]
##        else:
##            (myX, myY) = literal_eval(myXY)
##            myXyList = CreateXyList(port_it, mySortedPorts, theTolerance)
##            for xy_it in myXyList:
##                myPrintedPorts.add((myText, xy_it))
##            myOutput = myText + "," + myType + "," + "{:.12g}, {:.12g}".format(myX, myY)
##        myConnectionCount = 0
##        for instance_it in theInstanceOrder:
##            mySlicePort = GetSlicePort(instance_it, myXyList, myType, myText, thePortData)
##            if mySlicePort:
##                (mySliceText, myWinding) = mySlicePort
##                if myType.startswith("COIL"):
##                    mySliceText += "@" + myWinding
##                    if myConnectionCount == 0:
##                        myPortWinding = myWinding
##                    elif myPortWinding != myWinding:
##                        myPortOk = "X"
##                myOutput += "," + mySliceText
##                myConnectionCount += 1
##            else:  # No port on this chip
##                if myType.startswith("COIL"):  # Coils do not need ports on every chip
##                    myOutput += ", "
##                elif myType.startswith("TSV"):  # TSV must have port or blank on every chip
##                    if HasBlankPort(instance_it, myType, myXY, theTolerance,
##                                    myBlankPorts, thePortData):
##                        myOutput += ", "                   
##                    else:  # no matching port for this instance
##                        myOutput += ",?"
##                        myPortOk = "X"
##                else:  # dummy port
##                    # test for use!
##                    myOutput += ", "
##        if myConnectionCount < 2:  # All ports must have 2 or more connections
##            myPortOk = "X"
##        if myType.startswith("COIL"):  # Coil text must be unique
##            if myText in myUsedCoils or MultiplePorts(port_it, mySortedPorts, myPrintedPorts):
##                myPortOk = "X"
##            myUsedCoils.add(myText)
##        myLastText = myText
##        theOutputFile.write(myPortOk + "," + myOutput + "\n")
##
def main(argv):
    """Output a list of text for top level Calibre LVS

    usage: stic_text.py sticTextXmlFile [outputFile]
    """
    if not (1 <= len(argv) <= 2):
        print("usage: stic_text.py sticTextXmlFile [outputFile]")
        return
    print("STIC: Stacked Terminal Interconnect Check Text version 0.05.00")
    print("Reading settings...")
    myStackedChip = ET.parse(argv[0]).getroot()  # Parse the xml file.
    PrintParameters(myStackedChip)
#    myUserUnits = myStackedChip.find('userUnits').text
#    myTolerance = float(myStackedChip.find('tolerance').text)
    (myInstances, myNetConnections) = ReadTopCdlFile(myStackedChip)
#    myPortData = {}  # {(instanceName, "(x, y)", portType, topNet): (portName, winding), ...}
    if len(argv) == 2:
        print("Writing results to " + argv[1])
        myOutputFile = open(argv[1], "w")
    else:
        myOutputFile = sys.stdout
    for chip_it in myStackedChip.findall('chip'):
        PrintChipPorts(chip_it, myInstances, myNetConnections, myOutputFile)
#    mySortedInstances = []  # [instanceName, ...]
#    for instance_it in myStackedChip.findall('chip'):
#        mySortedInstances.append(instance_it.find('instanceName').text)
#    PrintReportHeader(myOutputFile, mySortedInstances, myInstances)
#    CheckPortData(myPortData, mySortedInstances, myInstances,
#                  myTolerance, myOutputFile, myNetConnections)

if __name__ == '__main__':
    main(sys.argv[1:])

#23456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789
