#! /usr/bin/env python
""" stic.py: Check the port correspondence of a stack of GDSII chips.

    Copyright 2106 D. Mitch Bailey

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

    requires python-gdsii, numpy
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
    if theElement.strans and theElement.strans & int('100000000000000', 2):
        print("mirrored")
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

def GetTransform(theOrientation, theTranslation, theScale=1.):
    """Return a transformation matrix for given orientation, translation, and scale.

    return: [(z0,y0,z0), (x1,y1,z1), (x2,y2,z2)] 
    """
    if theOrientation == "R0": 
        myRotation = np.array([(1.,0.,0.),(0.,1.,0.),(0.,0.,1.)])
    if theOrientation == "R90": 
        myRotation = np.array([(0.,1.,0.),(-1.,0.,0.),(0.,0.,1.)])
    if theOrientation == "R180": 
        myRotation = np.array([(-1.,0.,0.),(0.,-1.,0.),(0.,0.,1.)])
    if theOrientation == "R270": 
        myRotation = np.array([(0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)])
    if theOrientation == "MX": 
        myRotation = np.array([(1.,0.,0.),(0.,-1.,0.),(0.,0.,1.)])
    if theOrientation == "MXR90": 
        myRotation = np.array([(0.,1.,0.),(1.,0.,0.),(0.,0.,1.)])
    if theOrientation == "MY": 
        myRotation = np.array([(-1.,0.,0.),(0.,1.,0.),(0.,0.,1.)])
    if theOrientation == "MYR90": 
        myRotation = np.array([(0.,-1.,0.),(-1.,0.,0.),(0.,0.,1.)])
    myRotation.dtype = np.float64
    myTranslation = np.array([(1.,0.,0.),(0.,1.,0.),
                              (float(theTranslation[0][0]),float(theTranslation[0][1]),1.)])
    myTranslation.dtype = np.float64
    myScale = np.array([(float(theScale),0.,0.),(0.,float(theScale),0.),(0.,0.,1.)])
    myScale.dtype = np.float64
    return np.dot(np.dot(myScale, myRotation), myTranslation)

def Transform(thePointList, theTransform):
    """Returns a list of transformed points.

    return: [(x,y), ...]
    """
    myResult = []
    for point_it in thePointList:
        myPoint = [point_it[0], point_it[1], 1]
        myProduct = np.dot(myPoint, theTransform)
        myResult.append((myProduct[0], myProduct[1]))
    return myResult

def NormalizeBox(theBox):
    """Normalize (LowerLeft, UpperRight) box coordinates.

    return: [(left, bottom), (right, top)]
    """
    return [(min(theBox[0][0], theBox[1][0]), min(theBox[0][1], theBox[1][1])),
            (max(theBox[0][0], theBox[1][0]), max(theBox[0][1], theBox[1][1]))]

def IsBox(theBox):
    """True if points form a valid box."""
    if len(theBox) != 5: return False  # Must have 5 points.
    if theBox[0] != theBox[4]: return False  # Must start and stop at same point.
    myCheckX = True if theBox[0][1] != theBox[1][1] else False
    for point_it in range(4):
        if myCheckX:
            if theBox[point_it][0] != theBox[point_it+1][0]: return False
            if theBox[point_it][1] == theBox[point_it+1][1]: return False
        else:
            if theBox[point_it][0] == theBox[point_it+1][0]: return False
            if theBox[point_it][1] != theBox[point_it+1][1]: return False
        myCheckX = not myCheckX
    return True
            
def ReadTopCdlFile(theStackedChip):
    """Read a CDL netlist and return a list of top instances with nets.

    returns {instanceName: {'master': masterName, 'nets': portList}, ...}
    """
    myTopCell = theStackedChip.find('topCell').text
    myTopCdlFile = theStackedChip.find('topCdlFile').text
    mySubcktStartRE = re.compile("^\.[sS][uU][bB][cC][kK][tT]\s+(\S+)")
    myCdlFile = OpenFile(myTopCdlFile)
    mySaveInstances = False
    myLine = ""
    myInstances = {}
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
                elif not mySaveInstances and myInstances:  # finished top cell
                    break
            myLine = line_it
    if not myInstances:
        print("ERROR: Could not find subckt " + myTopCell + " in " + myTopCdlFile)
        raise NameError
    return myInstances

def BoxContains(theBox, thePoint):
    """True if theBox (2 tuple list) contains thePoint (tuple)."""
    return True if (theBox[0][0] <= thePoint[0] and theBox[1][0] >= thePoint[0]
                    and theBox[0][1] <= thePoint[1] and theBox[1][1] >= thePoint[1]) else False

def MapCdlPorts(theTopCell, theCdlFile, theParentNetList):
    """Return a dict of theTopCell ports mapped to parent nets.

    return: {portName: topNet, ...}
    """
    mySubcktStartRE = re.compile("^\.[sS][uU][bB][cC][kK][tT]\s+(\S+)")
    myCdlFile = OpenFile(theCdlFile)
    mySaveInstances = False
    myLine = ""
    myNetMap = {}
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
    return {}

def CreateStructureIndex(theGdsiiLib):
    """Return a dict of structure indices.

    return: {structureName: structureObject, ...}
    """
    myStructureIndex = {}
    for structure_it in theGdsiiLib:
        structure_it.processed = False
        myStructureIndex[structure_it.name.decode('utf-8')] = structure_it
    return myStructureIndex

def PromoteCellPorts(thePortLayers, thePortCellList, thePortType, theStructureIndex, theTopLayout, 
                     theOrientation="R0", theTranslation=[(0,0)]):
    """Promote low level cell ports to top level.

    return: [{'type': portType, 'xy': pointList[1], 'box': pointList[2]}, ...]
    errors: portLayers not in portCells, non-rectangular ports, non-boundary type ports
    """
    if not theTopLayout in theStructureIndex:
        print("ERROR: Could not find " + theTopLayout + " in GDS file.")
        raise NameError
    myStructure = theStructureIndex[theTopLayout]
    if not myStructure.processed:  # Do port checks for each structure only once.
        myStructure.ports = []
        for element_it in myStructure:
            if element_it.__class__.__name__ == 'SRef':
                myStructure.ports += PromoteCellPorts(thePortLayers, thePortCellList,
                                                      thePortType, theStructureIndex,
                                                      element_it.struct_name.decode('utf-8'),
                                                      GetOrientation(element_it), element_it.xy)
            elif element_it.__class__.__name__ == 'ARef':
                myXStep = (element_it.xy[1][0] - element_it.xy[0][0]) / element_it.cols
                myYStep = (element_it.xy[2][1] - element_it.xy[0][1]) / element_it.rows
                myY = element_it.xy[0][1]
                myOrientation = GetOrientation(element_it)
                myChildName = element_it.struct_name.decode('utf-8')
                for row_it in range(element_it.rows):
                    myX = element_it.xy[0][0]
                    for column_it in range(element_it.cols):
                        myStructure.ports += PromoteCellPorts(thePortLayers, thePortCellList,
                                                              thePortType, theStructureIndex,
                                                              myChildName,
                                                              myOrientation, [(myX, myY)])
                        myX += myXStep
                    myY += myYStep
            elif element_it.__class__.__name__ == 'Boundary':
                myLayerType = str(element_it.layer) + "-" + str(element_it.data_type)
                if myLayerType in thePortLayers:
                    if theTopLayout not in thePortCellList[myLayerType]:
                        print("Warning: Layer " + myLayerType + " in unexpected cell " 
                              + theTopLayout + " ignored.")
                    elif not IsBox(element_it.xy):
                        print("Warning: Layer-datatype " + myLayerType + " at " + str(element.xy)
                              + " in " + theTopLayout + " is not rectangular.")
                    else:
                       myStructure.ports.append({'type': thePortType[theTopLayout], 'xy': [(0,0)],
                                                  'box': [element_it.xy[0], element_it.xy[2]]})
            elif hasattr(element_it, 'layer') and hasattr(element_it, 'data_type'):
                myLayerType = str(element_it.layer) + "-" + str(element_it.data_type)
                if myLayerType in thePortLayers:
                    print("Warning: Layer-datatype " + myLayerType + " in unexpected element type "
                          + element_it.__class__.__name__ + ".")
        myStructure.processed = True
    myPorts = []
    if myStructure.ports:
        myTransform = GetTransform(theOrientation, theTranslation)
        for port_it in myStructure.ports:
            myPorts.append({'type': port_it['type'], 'xy': Transform(port_it['xy'], myTransform),
                'box': NormalizeBox(Transform(port_it['box'], myTransform))})
    return myPorts
        
def LoadGdsPorts(theChip, theStructureIndex, theTopLayout):
    """Return a list of ports from GDS library.

    return: [{'type': portType, 'xy': pointList[1], 'box': pointList[2]}, ...]
    """
    myPortLayers = []
    myPortCellList = {}
    myPortType = {}
    for port_it in theChip.findall('port'):
        myLayerType = port_it.find('layerNumber').text + "-" + port_it.find('dataType').text
        myPortLayers.append(myLayerType)
        myPortCellList[myLayerType] = []
        for portCell_it in port_it.findall('portCell'):
            myPortCellList[myLayerType].append(portCell_it.text)
            myPortType[portCell_it.text] = port_it.find('type').text
    myPortList = PromoteCellPorts(myPortLayers, myPortCellList, myPortType, 
                                  theStructureIndex, theTopLayout)
    return myPortList 

def LoadGdsText(theChip, theTopStructure):
    """Return a list of text on the top structure.

    return: [{'text': port, 'xy': pointList[1]}, ...]
    """
    myTextLayers = []
    for portText_it in theChip.findall('portText'):
        myLayerType = portText_it.find('layerNumber').text + "-" + portText_it.find('textType').text
        myTextLayers.append(myLayerType)
    myTextList = []
    for element_it in theTopStructure:
        if element_it.__class__.__name__ == 'Text':
            myLayerType = str(element_it.layer) + "-" + str(element_it.text_type)
            if myLayerType in myTextLayers:
                myTextList.append({'text': element_it.string.decode('utf-8'), 'xy': element_it.xy})
    return myTextList

def AssignPorts(thePortList, theTextList, theTopLayout):
    """Return a list of text with port type centered at port origin.

    return: [{'text': port, 'type': portType, 'xy': portCenter}, ...]
    errors: text mapped to multiple ports, text not mapped to any port.
    """
    myNamedPortList = []
    for text_it in theTextList:
        myTextFound = False
        for port_it in thePortList:
            if BoxContains(port_it['box'], text_it['xy'][0]):
                if myTextFound and myXY != port_it['xy']:
                    print("Warning: Text in multiple ports: " + text_it['text']
                          + " at " + str(myXY) + " and " + str(text_it['xy'])
                          + " in " + theTopLayout)
                else:
                    myNamedPortList.append({'text': text_it['text'],
                                            'type': port_it['type'],
                                            'xy': port_it['xy']})
                    port_it['assigned'] = True
                    myTextFound = True
                    myXY = port_it['xy']
        if not myTextFound:
            print("Warning: Unable to map text " + text_it['text'] + " at "
                  + str(text_it['xy']) + " in " + theTopLayout) 
    for port_it in thePortList:
        if not 'assigned' in port_it:  # Blank ports.
            myNamedPortList.append({'text': "",
                                    'type': port_it['type'],
                                    'xy': port_it['xy']})
    return myNamedPortList

def TranslateChipPorts(thePortList, theOrientation, theTranslation, theShrink):
    """Return a list of ports and transformed to final position in user units.
    return: [{'text': portName, 'type': portType, 'xy': position}, ...]
    """
    myInstancePortList = []
    myTransform = GetTransform(theOrientation, theTranslation, theShrink)
    for port_it in thePortList:
        myInstancePortList.append({'text': port_it['text'],
                                   'type': port_it['type'],
                                   'xy': Transform(port_it['xy'], myTransform)})
    return myInstancePortList

def GetGdsPortData(theChip, theUserUnits):
    """Translate GDS port data to final positions.

    return: {(instanceName, x, y, portType, topNet): portName, ...}
    Note: x, y in user units.
    """
    myTopLayoutName = theChip.find('topLayoutName').text
    myGdsFileName = theChip.find('gdsFileName').text
    myOrientation = theChip.find('orientation').text
    myShrink = theChip.find('shrink').text
    print(myTopLayoutName, myGdsFileName)
    myGdsFile = OpenFile(myGdsFileName, "rb")
    myGdsiiLib = Library.load(myGdsFile)
    myInternalDbuPerUU = myGdsiiLib.logical_unit / myGdsiiLib.physical_unit
    myOffset = theChip.find('offset')
    myX = float(myOffset.find('x').text) * myInternalDbuPerUU
    myY = float(myOffset.find('y').text) * myInternalDbuPerUU
    if theUserUnits == 'um':
        myOutputDbuPerUU = 1e-6 / myGdsiiLib.physical_unit
    elif theUserUnits == 'nm':
        myOutputDbuPerUU = 1e-9 / myGdsiiLib.physical_unit
    else:
        raise ValueError 
    myStructureIndex = CreateStructureIndex(myGdsiiLib)
    myPortList = LoadGdsPorts(theChip, myStructureIndex, myTopLayoutName)
    myTextList = LoadGdsText(theChip, myStructureIndex[myTopLayoutName])
    myNamedPortList = AssignPorts(myPortList, myTextList, myTopLayoutName)
    return TranslateChipPorts(myNamedPortList, myOrientation, [(myX, myY)],
                              float(myShrink) / myOutputDbuPerUU)

def PromoteChipPorts(theChip, theInstances, theUserUnits):
    """Promote individual chip ports to virtual top level.

    return: {(instanceName, x, y, portType, topNet): portName, ...}
    """
    myInstanceName = theChip.find('instanceName').text
    myCdlFile = theChip.find('cdlFileName').text
    myMasterSubckt = theInstances[myInstanceName]['master']
    myCdlPortMap = MapCdlPorts(myMasterSubckt, myCdlFile, theInstances[myInstanceName]['nets'])
    myGdsPortData = GetGdsPortData(theChip, theUserUnits)
    myMappedPorts = {}
    for port_it in myGdsPortData:
        if port_it['text']:
            myKey = (myInstanceName, "{0:.6g}".format(port_it['xy'][0][0]),
                     "{0:.6g}".format(port_it['xy'][0][1]), port_it['type'],
                     myCdlPortMap[port_it['text']])
            myMappedPorts[myKey] = port_it['text']
        else:  # unlabeled port
            myKey = (myInstanceName, "{0:.6g}".format(port_it['xy'][0][0]),
                     "{0:.6g}".format(port_it['xy'][0][1]), port_it['type'], "")
            myMappedPorts[myKey] = ""
    return myMappedPorts
    
def CheckPortData(thePortData, theInstances, theOutputFile):
    """Check the promoted ports' alignment."""
    myFinalPorts = set()
    for key_it in thePortData:  # Create top level port list.
        (myInstance, myX, myY, myType, myText) = key_it
        if myText != "":
            myFinalPorts.add((myText, myType, myX, myY))
    myOutput = "Check,Port,Type,X,Y"
    mySortedInstances = sorted(theInstances)
    for key_it in mySortedInstances:
        myOutput += "," + key_it + "(" + theInstances[key_it]['master'] + ")"
    theOutputFile.write(myOutput + "\n")
    for port_it in sorted(myFinalPorts):
        (myText, myType, myX, myY) = port_it
        myPortOk = "O"
        myOutput = myText + "," + myType + "," + myX + "," + myY
        for instance_it in mySortedInstances:
            myKey = (instance_it, myX, myY, myType, myText)
            if myKey in thePortData:
                myOutput += "," + thePortData[myKey]
            else:
                myBlankKey = (instance_it, myX, myY, myType, "")
                if myType == "TSV" and myBlankKey in thePortData:
                    myOutput += ", "
                else:  # no matching port for this instance
                    myOutput += ",?"
                    myPortOk = "X"
        theOutputFile.write(myPortOk + "," + myOutput + "\n")

def main(argv):
    """Check the correspondence of stacked GDSII chip text

    usage: stic.py sticXmlFile
    """
    if not (1 <= len(argv) <= 2):
        print("usage: stic.py sticXmlFile [outputFile]")
        return
    myStackedChip = ET.parse(argv[0]).getroot()  # Parse the xml file.
    myUserUnits = myStackedChip.find('userUnits').text
    myInstances = ReadTopCdlFile(myStackedChip)
    myPortData = {}
    for chip_it in myStackedChip.findall('chip'):
        myPortData.update(PromoteChipPorts(chip_it, myInstances, myUserUnits))
    if len(argv) == 2:
        print("Writing results to " + argv[1])
        myOutputFile = open(argv[1], "w")
    else:
        myOutputFile = sys.stdout
    CheckPortData(myPortData, myInstances, myOutputFile)

if __name__ == '__main__':
    main(sys.argv[1:])

#23456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789
