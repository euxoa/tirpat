vlc test.wav  --sout '#transcode{acodec=mp3}:standard{access=http,mux=mp3,ab=200,dst=:8080/sample}'
