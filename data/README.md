# data/

Everything in this folder except this file is ignored by git.

1. Download the AMPds2 whole-house electricity file from Harvard Dataverse
   (search "AMPds2", dataset by Makonin et al.). The whole-house meter file is
   usually named `Electricity_WHE.csv`.
2. Save it here as `ampds2_whe.csv`, or point `DATASET_PATH` in `.env` at it.
3. `utility.db` (the SQLite "utility database") is created here when the
   pipeline runs.

Cite the dataset in the report:
S. Makonin, B. Ellert, I. V. Bajic and F. Popowich, "Electricity, water, and
natural gas consumption of a residential house in Canada from 2012 to 2014,"
Scientific Data, vol. 3, 160037, 2016. doi:10.1038/sdata.2016.37
