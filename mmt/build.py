# Erzeugt elliott_wave_counter.mm aus src/ (Ebene 1 und 2 aus derselben Vorlage).
# Aufruf: python3 mmt/build.py mmt/elliott_wave_counter.mm
import sys, os
d=os.path.dirname(os.path.abspath(__file__))
hdr=open(os.path.join(d,"src","header.mm")).read()
lvl=open(os.path.join(d,"src","level.mm")).read()
ftr=open(os.path.join(d,"src","footer.mm")).read()
levels=[
 dict(S="1",L="1",MULT="atrMult",OFF="0.35",SIZE="labelSize",W1="1.0",W2="1.5",XSIZE="12.0",LNAME="Ebene 1",
      N1="1",N2="2",N3="3",N4="4",N5="5",Na="a",Nb="b",Nc="c",NA="A",NB="B",NC="C",NW="W",NX="X",NY="Y"),
 dict(S="2",L="2",MULT="atrMult2",OFF="0.9",SIZE="(labelSize + 4.0)",W1="1.5",W2="2.5",XSIZE="16.0",LNAME="Ebene 2",
      N1="①",N2="②",N3="③",N4="④",N5="⑤",Na="ⓐ",Nb="ⓑ",Nc="ⓒ",NA="Ⓐ",NB="Ⓑ",NC="Ⓒ",NW="Ⓦ",NX="Ⓧ",NY="Ⓨ"),
]
out=hdr
for L in levels:
    s=lvl
    for k,v in L.items(): s=s.replace("@"+k+"@",v)
    assert "@" not in s.replace("{2:.2}","").replace(" @ ","") , [x for x in s.split() if "@" in x][:5]
    out+=s
out+=ftr
open(sys.argv[1],"w").write(out)
print(len(out.splitlines()),"lines")
