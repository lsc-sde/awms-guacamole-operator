import kopf
import logging
import time
import asyncio
import kubernetes
import base64 
import os
import psycopg2


group = "xlscsde.nhs.uk"
kind = "AnalyticsWorkspaceBinding"
version = "v1"
api_version = f"{group}/{version}"
kube_config = {}

kubernetes_service_host = os.environ.get("KUBERNETES_SERVICE_HOST")
if kubernetes_service_host:
    kube_config = kubernetes.config.load_incluster_config()
else:
    kube_config = kubernetes.config.load_kube_config()

api_client = kubernetes.client.ApiClient(kube_config)
core_api = kubernetes.client.CoreV1Api(api_client)
dynamic_client = kubernetes.dynamic.DynamicClient(api_client)
custom_api = dynamic_client.resources.get(api_version = api_version, kind = kind)

def create_connection_group(cursor, name):
    cursor.execute("SELECT connection_group_id FROM public.guacamole_connection_group WHERE connection_group_name = %s;", name)
    connection_group_id = cursor.fetchone()
    if not connection_group_id:
        cursor.execute("INSERT INTO public.guacamole_connection_group (connection_group_name, type, max_connections, max_connections_per_user, enable_session_affinity) VALUES (%s, 1, 1, 1);", name)
        cursor.execute("SELECT connection_group_id FROM public.guacamole_connection_group WHERE connection_group_name = %s;", name)
        connection_group_id = cursor.fetchone()
        print(f"Connection group `{name}` has been created")
    return connection_group_id[0]

def create_connection(cursor, connection_group_id, name):
    cursor.execute("SELECT connection_id FROM public.guacamole_connection WHERE parent_id = %i and connection_name = %s;", connection_group_id, name)
    connection_id = cursor.fetchone()
    if not connection_id:
        cursor.execute("INSERT INTO public.guacamole_connection (parent_id, connection_name, protocol, failover_only) VALUES (%i, %s, 'vnc', 0);", connection_group_id, name)
        cursor.execute("SELECT connection_id FROM public.guacamole_connection WHERE parent_id = %i and connection_name = %s;", connection_group_id, name)
        connection_id = cursor.fetchone()
        print(f"Connection `{name}` has been created")
    return connection_id[0]

def set_connection_parameter(cursor, connection_id, name, value):
    cursor.execute("SELECT value FROM public.guacamole_connection_parameter WHERE connection_id = %i and parameter_name = %s;", connection_id, name)
    current_value = cursor.fetchone()
    if not current_value:
        cursor.execute("INSERT INTO public.guacamole_connection_parameter (connection_id, parameter_name) VALUES (%i, %s);", connection_id, name)
        print(f"Parameter `{name}` has been created")
    elif current_value != value:
        cursor.execute("UPDATE public.guacamole_connection_parameter SET parameter_value = %s WHERE connection_id = %i AND parameter_name %s;", connection_id, name, value)
        print(f"Parameter `{name}` has been updated")

def create_user(cursor, name):
    cursor.execute("SELECT entity_id FROM public.guacamole_entity where name = %s", name)
    entity_id = cursor.fetchone()
    if not entity_id:
        cursor.execute("INSERT INTO public.guacamole_entity NAME (name, type) VALUES (%s, 'USER');", name)
        cursor.execute("SELECT entity_id FROM public.guacamole_entity where name = %s", name)
        entity_id = cursor.fetchone()
    return entity_id[0]

def set_connection_permission(cursor, user_id, connection_id, permission = "READ"):
    cursor.execute("SELECT permission FROM public.guacamole_connection_parmission WHERE connection_id = %i and entity_id = %i;", connection_id, user_id)
    current_permission = cursor.fetchone()
    if not current_permission:
        cursor.execute("INSERT INTO public.guacamole_connection_parmission (connection_id, entity_id, permission) VALUES (%i, %i, %s);", connection_id, user_id, permission)
    elif current_permission[0] != permission:
        cursor.execute("UPDATE public.guacamole_connection_parmission SET permission = %s WHERE connection_id = %i and entity_id %i);", permission, connection_id, user_id)


@kopf.on.create(group=group, kind=kind)
@kopf.on.update(group=group, kind=kind)
@kopf.on.resume(group=group, kind=kind)
def bindingUpdated(status, name, namespace, spec, **_):   
    print(f"{name} on {namespace} has been updated")
    
    conn = psycopg2.connect(
        database=os.environ.get("DB_NAME"),
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        port=os.environ.get("DB_PORT")
        )
    cursor = conn.cursor()
    
    connection_group_id = create_connection_group(cursor, spec.workspace)
    print(f"{spec.workspace} group is {connection_group_id}")    
    connection_id = create_connection(cursor, connection_group_id, spec.username)
    user_id = create_user(cursor, spec.username)
    print(f"{spec.workspace} connection is {connection_id}")    
    set_connection_parameter(cursor, connection_id, "disable-copy", "true")
    set_connection_parameter(cursor, connection_id, "disable-paste", "true")
    set_connection_parameter(cursor, connection_id, "hostname", "localhost")
    set_connection_parameter(cursor, connection_id, "username", "test")
    set_connection_parameter(cursor, connection_id, "password", "test")
    set_connection_permission(cursor, user_id, connection_id)
    conn.close()

@kopf.on.delete(group=group, kind=kind)
def bindingDeleted(status, name, namespace, spec, **_):   
    print(f"{name} on {namespace} has been deleted")
