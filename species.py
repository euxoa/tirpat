import glob, re, argparse, hashlib, subprocess, time
import pandas as pd

dscr="""
A script for displaying summaries of BirdNET-Analyzer observations from a buch of 
CSV-style audio files, with YYYYmmdd_hhmmss in their file names. Also produces
audio clips of observations by calling sox.
"""

eplg="""
Examples:

   # Run with defaults to get a list of obs per species
   python species.py res/res-* 

   # Only owls
   python species.py --species 'owl|Strix' res/res-*

   # Five records per species, min 60 seconds between occurrences
   python species.py -l 60 -n 5

   # Lower confidence threshold to .7, but require full set (default 3) 
   # per species to show
   python species.py -l 60 -n 5 --full-only

   # Like above, but instead of a list, produce clips
   python species.py -l 60 -n 5 --full-only --clips raw_dir clips_dir

   # Observation counts of those species
   python species.py -l 60 -n 5 --full-only --counts

"""


parser = argparse.ArgumentParser(description=dscr, epilog=eplg,
                                 formatter_class=argparse.RawTextHelpFormatter)


parser.add_argument("-p", "--pmin", type=float, default=0.9,
                    help="confidence, minimum (default: 0.9)")
parser.add_argument("-l", "--minlag", type=float, default=2.0,
                    help="seconds, min between adjacent included rows (default: 2.0)")
parser.add_argument("-n", "--nrows", type=int, default=3,
                    help="max number of rows per species (default: 3)")
parser.add_argument('--raw', action=argparse.BooleanOptionalAction,
                    help="raw observations, skips ordering, argmax(p) logic and max number of lines")
parser.add_argument('--full-only', action=argparse.BooleanOptionalAction,
                    help="require max number (nrows) of lines for species")
parser.add_argument('--nonfull-only', action=argparse.BooleanOptionalAction,
                    help="require less than max number (nrows) of lines for species")
parser.add_argument('--species',
                    help="species regex to filter with")
parser.add_argument("--output-duration", type=float, default=20,
                    help="length of clips, in seconds")
parser.add_argument("--output-type", type=str, default='flac',
                    help="type of clips, as recognized by sox")
parser.add_argument("--timezone", type=str, default=time.tzname[0],
                    help="time zone for species lists and clip names (UTC in clip metadata)")
parser.add_argument('--clip', nargs=2, help='dir of orig. audio and dir of clips')
parser.add_argument('--clap', action=argparse.BooleanOptionalAction,
                    help="clip, assuming origs are in 'raw' and clips are in 'clips'")
parser.add_argument('--counts', action=argparse.BooleanOptionalAction,
                    help="accepted obs counts per species")
parser.add_argument("input_files", nargs="+",
                    help="input files")

args = parser.parse_args()

pmin = args.pmin
minlag = args.minlag
nrows = args.nrows
sp_rex = args.species
input_files = args.input_files
output_type = args.output_type
output_duration = args.output_duration
timezone = args.timezone


if args.clap:
    do_clip, raw_dir, clip_dir = True, "raw", "clips"
elif args.clip is not None:
    do_clip, raw_dir, clip_dir = True, args.clip[0], args.clip[1]
else:
    do_clip, raw_dir, clip_dir = False, None, None

# pd.set_option('display.max_rows', None)

def deduplicate(d, var, threshold):
    """
    Find rows in d that are closer to each other than threshold by values of var,
    then select only first row within each such adjacency group.
    """
    d = d.sort_values(var)
    return d[~d[var].diff(periods=1).abs().lt(threshold).values]

def deduplicate2(d, var, threshold, var_max):
    """
    Find rows in d that are closer to each other than threshold by values of var,
    then select the row highest in value of var_max in each 'adjacency group'.
    """
    r = d.sort_values(var).\
        groupby((~d[var].diff(periods=1).abs().lt(threshold).values).cumsum(), group_keys=True).\
        apply(lambda x: x.nlargest(1, var_max))#x.loc[x[var_max].idxmax()])
    return r

d = pd.concat([pd.read_csv(f, header=0).assign(file=f)
               for f in input_files]) # was glob.glob(res/res-*.txt")

d.rename(columns = {"Scientific name" : "species",
                    "Common name" : "cname",
                    "Start (s)" :"start", "End (s)" : "end", "Confidence" : "p"}, inplace=True)

# Filter by confidencce, and maybe by species
d = d.loc[d['p'] > pmin]
if sp_rex is not None:
    d = d.loc[d.species.str.contains(sp_rex) | d.cname.str.contains(sp_rex) ]

d['t_center'] = (d['start'] + d['end'])/2
d['t'] = (pd.to_datetime(d.file, format="%Y%m%d_%H%M%S", exact=False, utc=True) +
          pd.to_timedelta(d['t_center'], unit='s'))
    

# .droplevel(0) or .droplevel('species') is nice but crashes
# if you have zero species (empty data frame after species rex for example).
# The group_keys thing is needed for the same reason.
# With grouping, another way around would be groupby(..., as_index=False), then
# you don't need to reset the index afterwards.

# So, first take only trustworthy lines, and remove adjacent obs (by selecting argmax(p) of those)
d_spaced = d.groupby('species', group_keys=True).\
          apply(lambda x: deduplicate2(x, 't', pd.to_timedelta(minlag, unit='s'), 'p')).\
          reset_index(drop=True)

# Counts (maybe not needed)
d_counts = d_spaced.groupby('species', as_index=False).size().rename(columns={'size':'count'})

if args.raw:
    d_samples = d
else:
# Head, or only the best rows.
    d_samples = d_spaced.groupby('species', group_keys=True).\
        apply(lambda x: x.sort_values('p', ascending=False).head(nrows)).\
        reset_index(drop=True)

if args.full_only:
    d_samples = d_samples.groupby('species').filter(lambda x: x.shape[0] == nrows)
if args.nonfull_only:
    d_samples = d_samples.groupby('species').filter(lambda x: x.shape[0] < nrows)

d_samples['nicetime'] = d_samples.t.dt.tz_convert(timezone).dt.strftime('%A %d.%m. %H:%M') # For output
d_samples['utctime'] = d_samples.t.dt.strftime('%Y-%m-%d %H:%M UTC') # For clip metadata
d_samples['nicetime2'] = d_samples.t.dt.tz_convert(timezone).dt.strftime('%Y%m%d_%H%M') # For clip names

if not do_clip:
    # Just show the obs list or counts
    if args.counts:
        # Counts with max p, for species on the list (note potential --full-only)
        d_show = d_samples.groupby(['species', 'cname'], as_index=False)['p'].max().\
            merge(d_counts).sort_values('count', ascending=False)
    else:
        # Just best observations per species
        d_show = d_samples.loc[:,('species' ,'cname', 'p', 'nicetime')]
    print(d_show.to_string(index=False))
else:
    # Make clips
    date_ptrn = re.compile(r"(\d{8}_\d{6})")
    d_samples['file_ptrn'] = [re.search(date_ptrn, file).group(1) for file in d_samples['file']]
    p2raw   = { re.search(date_ptrn, file).group(1) : file for file in glob.glob(f'{raw_dir}/*') }

    for idx, r in d_samples.iterrows():
        file_ptrn = r['file_ptrn']
        orig = p2raw.get(r['file_ptrn'])
        if orig:
            tmax = float(subprocess.run(['soxi', '-D', orig],
                                                 stdout=subprocess.PIPE, text=True).stdout)
            start, p, species, utctime = r['start'], r['p'], r['species'], r['utctime']
            t_center, nicetime2 = r['t_center'], r['nicetime2']
            # Comment goes to the file as metadata.
            comment = (f"species={species}, confidence={p}, time={utctime}, "
                       f"orig_file={orig}, t_center={t_center}")
            hsh = f"{int(100 * p)}{hashlib.md5(comment.encode('latin1')).hexdigest()[:2]}"
            clip = f"{clip_dir}/{r['cname']}_{nicetime2}_{hsh}.{output_type}"
            th = output_duration / 2 
            t0, pd0 = (virt0, 0) if (virt0 := t_center - th) > 0 else (0, -virt0) 
            t1, pd1 = (virt1, 0) if (virt1 := t_center + th) < tmax else (tmax, virt1 - tmax)
            print(f"Clipping {orig} to {clip}, @{t_center} pads {pd0} {pd1}")
            sox1 = subprocess.Popen(['sox', orig, 
                                     '-t', 'flac', '-', # output (stdout)
                                     'trim', str(t0), str(t1-t0),
                                     'highpass', str(100),
                                     'norm', str(-4)],
                                    stdout=subprocess.PIPE)
            sox2 = subprocess.run(['sox', '-', 
                                   '--comment', comment, # add metadata
                                   '-b', '16',
                                   clip, # output file (final)
                                   'pad', str(pd0), str(pd1)],
                                  stdin=sox1.stdout)
        else:
            print("No raw match for", row['file'])


            
        

