import pandas as pd
# import glob
import argparse

parser = argparse.ArgumentParser()

parser.add_argument("-p", "--pmin", type=float, default=0.9,
                    help="confidence, minimum (default: 0.9)")
parser.add_argument("-l", "--minlag", type=float, default=2.0,
                    help="seconds, min between adjacent included rows (default: 2.0)")
parser.add_argument("-n", "--nrows", type=int, default=3,
                    help="max number of rows per species (default: 3)")
parser.add_argument('--full', action=argparse.BooleanOptionalAction,
                    help="require full number of lines for species")
parser.add_argument('--species',
                    help="species regex")
parser.add_argument("input_files", nargs="+",
                    help="input files")
parser.add_argument('--clip', nargs=2, help='clip input and output directories')

args = parser.parse_args()

pmin = args.pmin
minlag = args.minlag
nrows = args.nrows
req_full = args.full
sp_rex = args.species
input_files = args.input_files

if args.clip is not None:
    raw_dir = args.clip[0] 
    clip_dir = args.clip[1]

# pd.set_option('display.max_rows', None)

def deduplicate(d, var, threshold):
    d = d.sort_values(var)
    # FIXME: This should actually calculate a cumsum, group by that,
    # and select max or some such by another column.
    # Note: the negation needed, otherwise first NaN goes wrong.
    return d[~d[var].diff(periods=1).abs().lt(threshold).values]

d = pd.concat([pd.read_csv(f, header=0).assign(file=f)
               for f in input_files]) # was glob.glob(res/res-*.txt")

d.rename(columns = {"Scientific name" : "species",
                    "Common name" : "cname",
                    "Start (s)" :"start", "End (s)" : "end", "Confidence" : "p"}, inplace=True)

# FIXME: filter by species
if sp_rex is not None:
    d = d.loc[d.species.str.contains(sp_rex) | d.cname.str.contains(sp_rex) ]

d['t_within'] = (d['start'] + d['end'])/2
d['t'] = (pd.to_datetime(d.file, format="%Y%m%d_%H%M%S", exact=False, utc=True) +
          pd.to_timedelta(d['t_within'], unit='s'))
d['nicetime'] = d.t.dt.tz_convert('EET').dt.strftime('%A %d.%m. %H:%M')
    

# .droplevel(0) or .droplevel('species') is nice but crashes
# if you have zero species (empty data frame) after species rex for example.
# the group_keys thing is needed for the same reason.
# So, first take only trustworthy lines, and remove adjacent obs.
d2 = d.pipe(lambda df: df[df['p'] > pmin]).\
    groupby('species', group_keys=True).\
    apply(lambda x: deduplicate(x, 't', pd.to_timedelta(minlag, unit='s'))).\
    reset_index(drop=True)
# Head, or only the best rows.
d2 = d2.groupby('species', group_keys=True).\
    apply(lambda x: x.sort_values('p', ascending=False).head(nrows)).\
    reset_index(drop=True)
# For output only (FIXME, this should be later).
d2 = d2.loc[:,('species' ,'cname', 'p', 'nicetime')]

if req_full:
    d2 = d2.groupby('species').filter(lambda x: x.shape[0] == nrows)


print(d2.to_string())

