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
    myStructureIndex = CreateStructureIndex(myGdsiiLib)
    print("Loading ports...")
    if myLayoutName not in myStructureIndex:
        print("ERROR: Could not find " + myLayoutName + " in " + myGdsFileName)
        raise NameError
    myTextList = LoadGdsText(theChip, myStructureIndex[myLayoutName])
    print("Assigning text...")
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
    for port_it in myGdsPortData:
        if port_it['text'] in myCdlPortMap:
            theOutputFile.write(" ".join(("LAYOUT TEXT",
                                          "\"" + myCdlPortMap[port_it['text']] + "\"",
                                          port_it['xy'], port_it['layer'], "\n")))
            myPrintedPorts.add(port_it['text'])     
        else:
            print("WARNING: layout port " + port_it['text']
                  + " at (" + port_it['xy'] + ") of " + theChip.find('layoutName').text
                  + " in " + theChip.find('gdsFileName').text
                  + " not in subckt " + myInstanceName + "(" + myMasterSubckt + ") of " + myCdlFile)
    for net_it in myCdlPortMap:  # Check for CDL nets missing ports
        if net_it not in myPrintedPorts:
            print("WARNING: net " + net_it + " of " + myInstanceName + "(" + myMasterSubckt + ") of "
                  + myCdlFile + " has no layout text")

def main(argv):
    """Output a list of text for top level Calibre LVS

    usage: stic_text.py sticTextXmlFile [outputFile]
    """
    if not (1 <= len(argv) <= 2):
        print("usage: stic_text.py sticTextXmlFile [outputFile]")
        return
    print("STIC: Stacked Terminal Interconnect Check Text version 0.09.00")
    print("Reading settings...")
    myStackedChip = ET.parse(argv[0]).getroot()  # Parse the xml file.
    PrintParameters(myStackedChip)
    (myInstances, myNetConnections) = ReadTopCdlFile(myStackedChip)
    if len(argv) == 2:
        print("Writing results to " + argv[1])
        myOutputFile = open(argv[1], "w")
    else:
        myOutputFile = sys.stdout
    for chip_it in myStackedChip.findall('chip'):
        PrintChipPorts(chip_it, myInstances, myNetConnections, myOutputFile)

if __name__ == '__main__':
    main(sys.argv[1:])

#23456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789*123456789
