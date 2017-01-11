# stic

Stacked-chip Terminal Connectivity Check

Checks the terminal positions on a set of stacked chips for alignment.

Input is an xml file defining
- top CDL subckt name
- top CDL file name
- output user units (um/nm)
- offset tolerance in user units
- each chip has the following
  - instance name in top CDL subckt
  - subcircuit name in CDL file (default from top CDL)
  - CDL file name (default top CDL)
  - top GDSII structure name
  - GDSII file name
  - port definitions (recognition layers)
    - layer number
    - datatype number
    - port type (TSV/COIL)
    - port cell names
    - top port text (optional)
      - text layer
      - texttype number
    
stic.xsd is the schema for the xml file



