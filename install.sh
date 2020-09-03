#!/bin/sh

if [ $EUID -ne 0 ]; then
	echo "Please run script as root."
	exit 1
fi
cp ./etc/air-alert.json /etc/air-alert.json