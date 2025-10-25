sudo mkdir /mnt/T4
sudo mount /dev/sdb2 /mnt/T4
nohup rsync -av  ~/tirpat/ /mnt/T4/tirpat
