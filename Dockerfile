FROM python:3.12-alpine

ENV DB_NAME="guacamole"
ENV DB_HOST="k3d-postgres-postgresql.postgres-on-k3d.svc.cluster.local"
ENV DB_USER="guacamole"
ENV DB_PASS="guacamole"
ENV DB_PORT="5432"
ENV IMAGE_NAME="lscsde/analytics-vnc-client:0.1.5"

RUN apk add gcc
RUN pip install --upgrade pip
RUN pip install kubernetes
RUN pip install psycopg2-binary
RUN MULTIDICT_NO_EXTENSIONS=1 pip install kopf
ADD ./service.py /src/service.py

CMD kopf run /src/service.py -A --standalone
