# tirpat
Minimal scripts to run BirdNET Analyser continuously on USB audio, in Raspberry Pi. 

This requires at least the https://github.com/kahst/BirdNET-Analyzer, several Python packages, sox. 

`lsusb` is useful, `arecord -l` even more so to find correct device numbers. 
Also, you need to know the sample format etc., but either `arecord` or `sox` shows them to you somehow. 
