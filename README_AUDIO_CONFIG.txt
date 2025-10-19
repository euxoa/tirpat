You need to disable audio from /boot/config.txt maybe, and then the USB wire, connect it properly. ;)

lsusb
arecord -l shows you right device numbers

What chatGPT says about flacs:
arecord -D hw:1,0 -c 1 -r 48000 -f cd -t wav - | sox -t wav - -c 1 -r 48000 -t flac recording.flac
... but remember the device numbers
