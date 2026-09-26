ARG BUILD_FROM
FROM $BUILD_FROM

# Python + BlueZ (bluetoothctl for one-time bonding) + BLE/MQTT libs.
# Versions are pinned: the image is built on your Home Assistant at install/update
# time, so unpinned packages would silently pull whatever is newest that day (a
# breaking bleak / aioesphomeapi major would break the add-on on the next update).
# All of these ship musllinux wheels for amd64 + aarch64 (no compiler needed).
RUN apk add --no-cache python3 py3-pip bluez ca-certificates \
    && pip3 install --no-cache-dir --break-system-packages \
       bleak==3.0.2 \
       paho-mqtt==2.1.0 \
       aiohttp==3.14.3 \
       aioesphomeapi==46.3.0 \
       zeroconf==0.151.3 \
       certifi==2026.7.22

COPY run.sh /run.sh
COPY bosch_mqtt_reader.py /bosch_mqtt_reader.py
COPY skus.json /skus.json
COPY comp_init.txt /comp_init.txt
COPY bike.png /bike.png
COPY leaflet.js /leaflet.js
COPY leaflet.css /leaflet.css
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
