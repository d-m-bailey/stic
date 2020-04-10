# stic

Stacked-chip Terminal Interconnectivity Check

Checks the terminal positions for alignment on a set of stacked chips.

TSV ports must exist on every chip (blank ports allowed).

COIL ports must have the same winding direction.

<details>
<summary>Input is an xml file defining the following:</summary>
  
+ top CDL subckt name
+ top CDL file name
+ output user units (um/nm)
+ offset tolerance in user units
+ each chip has the following
  - instance name in top CDL subckt
  - subcircuit name in CDL file (default from top CDL)
  - CDL file name (default top CDL)
  - top GDSII structure name
  - GDSII file name
  - text file for port definitions (optional)
  - orientation of chip (R0, R90, R180, R270, MX, MXR90, MY, MYR90)
  - x, y offset of origin (0.0001 increments)
  - shrink percentage (default 1.0, 0.001 increments)
  - port definitions (recognition layers)
    - port type (TSV/COIL)
    - layer number
    - datatype number
    - port cell names
    - top port text (optional)
      - text layer
      - texttype number
</details>
      
Output is a CSV file listing each port, xy, port type, chip connection(winding/size) and check result.
    
stic.xsd is the schema for the xml file

Installation
------------

Requires python-gdsii, numpy

    pip install http://pypi.python.org/packages/source/p/python-gdsii/python-gdsii-0.2.1.tar.gz
    pip install numpy

No installation. After downloading, 

    python stic.py [-t] XMLfile [outputFile]

Support
-------

If you are having issues, please let us know.
Contact us at: cvc@shuharisystem.com

License
-------

The project is licensed under the GPLv3 license.

