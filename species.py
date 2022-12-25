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
parser.add_argument("input_files", nargs="+",
                    help="input files")

args = parser.parse_args()

pmin = args.pmin
minlag = args.minlag
nrows = args.nrows
req_full = args.full
input_files = args.input_files

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

d['t_within'] = (d['start'] + d['end'])/2
d['t'] = (pd.to_datetime(d.file, format="%Y%m%d_%H%M%S", exact=False, utc=True) +
          pd.to_timedelta(d['t_within'], unit='s'))
d['nicetime'] = d.t.dt.tz_convert('EET').dt.strftime('%A %d.%m. %H:%M')
    

d2 = d.pipe(lambda df: df[df['p'] > pmin]).\
    groupby('species').apply(lambda x: deduplicate(x, 't', pd.to_timedelta(minlag, unit='s'))).droplevel((0)).\
    groupby('species').apply(lambda x: x.sort_values('p', ascending=False).head(nrows)).droplevel(0).\
    loc[:,('species' ,'cname', 'p', 'nicetime')]

if req_full:
    d2 = d2.groupby('species').filter(lambda x: x.shape[0] == nrows)


print(d2.to_string())

