# tirpat
Minimal scripts to run BirdNET Analyzer continuously on USB audio, for example in Raspberry Pi 4,
and to get compact species and observation lists, and to clip audio of those
for storing or checking in, e.g., Audacity.

This requires at least Python 3 (3.9+ I think), the 
[BirdNet Analyzer](https://github.com/kahst/BirdNET-Analyzer), several Python packages like pandas,
and the command line utility sox.

For continuous recording, use `obsloop.py`, run in background. To set up:

* `lsusb` is useful, `arecord -l` even more so to find correct device numbers. 

* Also, you need to know the sample format etc., but either `arecord` or `sox` shows them to you somehow. 

* The script `obsloop.sh` has parameters at the start, and more in `arecord` and `analyze.py` calls, you
need to check them and edit approriately. First run `arecord` manually, then do the same with the analyzer
to find correct parameters. Finally, run the whole script with `duration` set short to see everything it works. 

The script `species.py` is more generally useful for checking observations from CSV-style result files
of the BirdNET Analyzer, and for splitting high-confidence samples from the original audio files to be
further inspected with, e.g., Audacity. The intention is that you can then archive the original audio
away or archive it.

See `python species.py --help` for examples. 

`species.py` has a command-line interface with several options. `--counts` may be useful, and of course `--clip` 
once you have found out a good set of clippable obsevations by using the script with any of these arguments. 
Defaults are sensitive, but you may play with required minimum lag of observations within species, `-l seconds`, 
and maximum number of lines `-n`, minimun confidence level `-p` (I find values 0.7–0.9 useful), 
and also note `--full-only` to discard species with just few possible appearances. 

The script assumes an UTC timestamp to be included in the audio file names, and CSV file names
from the BirdNET Analyzer too. If you have an Audiomoth, it uses similar naming conventions. 

All this is provided as is, no support, somewhat work in progress, under a typical OS licence, in the hope that
it would be helpful in intended purpose and good material for further development. 

Note that there is [https://birdnetpi.com](BirdNET-Pi) for those who want a complete and flashy solution with 
less flexibility. Also, when I'm writing this, BirdNET-Pi still depends on old Tensorflow models. 

