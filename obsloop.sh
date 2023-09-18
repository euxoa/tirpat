#!/bin/bash

file_prefix=mokki
ba=BirdNET-Analyzer
raw_dir=raw
res_dir=res
duration=3600

get_current_qweek() {
    month=$(date +%-m)
    day_of_month=$(date +%-d)

    # Calculate the number of days in the current month
    # days_in_month=$(date --date="$year-$month-01 + 1 month - 1 day" +%d)

    # Calculate the current qweek based on the current day of the month
    current_qweek=$(((month - 1) * 4 + (day_of_month - 1) / 7))

    # Output the current qweek
    echo "$current_qweek"
}


while true
do
    # Get the current UTC time to use in file names
    file_basename=$file_prefix-$(date -u +"%Y%m%d_%H%M%S")
    # ... and week as understood by BirdNet (48 weeks per year)
    qweek=$(get_current_qweek)

    # Rotate stereo files
    # find ./stereo -name "*.flac" -type f -mtime +1 -exec rm -f {} \;
    for i in {24..1}
    do
	mv -f "stereo/file$i.flac" "stereo/file$(($i+1)).flac" > /dev/null 2>&1
    done
    
    # Record audio for one hour (-d 3600) using the Røde USB audio interface (-D hw:x,x)
    # at a sample rate of 48000 Hz (--format=S24_3LE -r 48000)
    # in stereo (-c 2)
    # and pipe ...
    arecord -D hw:1,0 -d $duration -r 48000 --format=S24_3LE -c 2 - |

    # Save a stereo version
    tee >(sox -t wav - -c 2 -r 48000 -t flac stereo/file1.flac highpass 10 norm -3) |

    # Convert the audio from the pipe to a mono FLAC file (-c 1) and save.
    sox -t wav - -c 1 -r 48000 -t flac $raw_dir/$file_basename.flac highpass 10 &&

    # Run Birdnet Analyzer in the background
    (python3 $ba/analyze.py --i $raw_dir/$file_basename.flac --o res/res-$file_basename.txt \
         --lat 61.46 --lon 29.39 --week $qweek --overlap 1.5 --locale fi --rtype csv --threads 1 & )
done
