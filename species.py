import pandas as pd
import glob

# pd.set_option('display.max_rows', None)

d = pd.concat([pd.read_csv(f, header=0).assign(file=f)
               for f in glob.glob("res/res-*.txt")])
d.rename(columns = {"Scientific name" : "species",
                    "Common name" : "cname",
                    "Start (s)" :"t0", "End (s)" : "t1", "Confidence" : "p"}, inplace=True)

def deduplicate(d, var, threshold):
    d = d.sort_values(var)
    # Note: the negation needed, otherwise first NaN goes wrong.
    return d[~d[var].diff(periods=1).abs().lt(threshold).values]
    

d2 = d.pipe(lambda df: df[df['p']>.9]).\
    groupby(['species','file']).apply(lambda x: deduplicate(x, 't0', 2.0)).droplevel((0,1)).\
    groupby('species').apply(lambda x: x.sort_values('p', ascending=False).head(3)).droplevel(0).\
    loc[:,('species' ,'cname', 'p', 't0', 'file')]

print(d2)
