C Example geometry for Methods 2.3: disk with one central hole and six peripheral holes
C Units are cm. Dimensions correspond to:
C outer radius = 40 mm, thickness = 10 mm,
C center hole radius = 6 mm, peripheral-hole radius = 4 mm,
C bolt-circle radius = 28 mm.
1 0 -1 2 -3 4 5 6 7 8 9 10 imp:n=1 $ disk minus one central hole and six peripheral holes
99 0 1:-2:3:-4:-5:-6:-7:-8:-9:-10 imp:n=0 $ outside graveyard

1  CZ 4.0
2  PZ -0.5
3  PZ 0.5
4  CZ 0.6
5  C/Z 2.8 0.0 0.4
6  C/Z 1.4 2.424871 0.4
7  C/Z -1.4 2.424871 0.4
8  C/Z -2.8 0.0 0.4
9  C/Z -1.4 -2.424871 0.4
10 C/Z 1.4 -2.424871 0.4

mode n
