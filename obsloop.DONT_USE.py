# This is a version translate with chatGPT.
# Not tested, not maybe up to date.

import datetime
import subprocess

duration = 3600
file_prefix = "home"
raw_dir = "raw"
res_dir = "res"
ba = "ba" # Set the path to the Birdnet Analyzer script

def get_current_qweek():
    # Get the current month and year
    month = datetime.datetime.now().month
    year = datetime.datetime.now().year

    # Calculate the current qweek based on the current month and day of the month
    current_qweek = (month - 1) * 4 + datetime.datetime.now().day // 7

    # Return the current qweek
    return current_qweek


qweek = get_current_qweek()

while True:
    # Get the current UTC time to use in file names
    file_basename = file_prefix + "-" + datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Record audio for one hour (-d 3600) using the Røde USB audio interface (-D hw:2,0)
    # at a sample rate of 48000 Hz (--format=S24_3LE -r 48000)
    # in stereo (-c 2)
    # and pipe the output to the sox command
    arecord_process = subprocess.Popen(["arecord", "-D", "hw:2,0", "-d", str(duration),
                                        "-r", "48000", "--format=S24_3LE", "-c", "2", "-"],
                                       stdout=subprocess.PIPE)

    # Convert the audio from the pipe to a mono FLAC file (-c 1) and save.
    sox_process = subprocess.Popen(["sox", "-t", "wav", "-", "-c", "1", "-r", "48000", "-t", "flac",
                                    raw_dir + "/" + file_basename + ".flac"],
                                   stdin=arecord_process.stdout, stdout=subprocess.PIPE)

    # Run Birdnet Analyzer in the background
    birdnet_analyzer_process = subprocess.Popen(["python3", ba + "/analyze.py",
                                                 "--i", raw_dir + "/" + file_basename + ".flac",
                                                 "--o", res_dir + "/res-" + file_basename + ".txt",
                                                 "--lat", "60", "--lon", "20", "--week", str(qweek),
                                                 "--overlap", "1.5", "--locale", "fi",
                                                 "--rtype", "csv", "--threads", "1"],
                                                stdout=subprocess.PIPE)

    
