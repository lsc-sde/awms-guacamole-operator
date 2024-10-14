import kopf
import logging
import time
import asyncio
import base64 
import os
import psycopg2
import base64
import datetime
from uuid import uuid5, NAMESPACE_URL
from kubernetes import client, config, dynamic
from urllib import parse

status_provisioning : str = "PROVISIONING"
status_ready : str = "READY"
status_active : str = "ACTIVE"
media_types_merge_patch : str = "application/merge-patch+json"

group : str = "xlscsde.nhs.uk"
kind : str = "AnalyticsWorkspaceBinding"
plural : str = "analyticsworkspacebindings"
version : str = "v1"
max_connections : int = 1000
max_connections_per_user : int = 1000
api_version : str = f"{group}/{version}"
kube_config = {}

kubernetes_service_host = os.environ.get("KUBERNETES_SERVICE_HOST")
if kubernetes_service_host:
    kube_config = config.load_incluster_config()
else:
    kube_config = config.load_kube_config()

api_client = client.ApiClient(kube_config)
core_api = client.CoreV1Api(api_client)
dynamic_client = dynamic.DynamicClient(api_client)
custom_api = dynamic_client.resources.get(api_version = api_version, kind = kind)
custom_objects_api = client.CustomObjectsApi()
apps_v1 = client.AppsV1Api(api_client)

def create_connection_group(body, cursor, name : str):
    cursor.execute("SELECT connection_group_id FROM public.guacamole_connection_group WHERE connection_group_name = %s;", [ name ])
    connection_group_id = cursor.fetchone()
    if not connection_group_id:
        cursor.execute("INSERT INTO public.guacamole_connection_group (connection_group_name, type, max_connections, max_connections_per_user, enable_session_affinity) VALUES (%s, 'ORGANIZATIONAL', %s, %s, true);", [ name, max_connections, max_connections_per_user ])
        cursor.execute("SELECT connection_group_id FROM public.guacamole_connection_group WHERE connection_group_name = %s;", [ name ])
        connection_group_id = cursor.fetchone()
        kopf.info(body, reason='DbUpsert', message=f"Connection group `{name}` has been created")

    return connection_group_id[0]

def create_connection(body, cursor, connection_group_id : int, name : str):
    cursor.execute("SELECT connection_id FROM public.guacamole_connection WHERE parent_id = %s and connection_name = %s;", [ connection_group_id, name ])
    connection_id = cursor.fetchone()
    if not connection_id:
        cursor.execute("INSERT INTO public.guacamole_connection (parent_id, connection_name, protocol, failover_only) VALUES (%s, %s, 'vnc', false);", [ connection_group_id, name ])
        cursor.execute("SELECT connection_id FROM public.guacamole_connection WHERE parent_id = %s and connection_name = %s;", [ connection_group_id, name ] )
        connection_id = cursor.fetchone()
        kopf.info(body, reason='DbUpsert', message=f"Connection `{name}` has been created")
    return connection_id[0]

def set_connection_parameter(body, cursor, connection_id : int, name : str, value: str):
    cursor.execute("SELECT parameter_value FROM public.guacamole_connection_parameter WHERE connection_id = %s and parameter_name = %s;", [connection_id, name])
    current_value = cursor.fetchone()
    if not current_value:
        cursor.execute("INSERT INTO public.guacamole_connection_parameter (connection_id, parameter_name, parameter_value) VALUES (%s, %s, %s);", [connection_id, name, value])
        kopf.info(body, reason='DbUpsert', message=f"Parameter `{name}` has been created")
    elif current_value != value:
        cursor.execute("UPDATE public.guacamole_connection_parameter SET parameter_value = %s WHERE connection_id = %s AND parameter_name = %s;", [value, connection_id, name])
        kopf.info(body, reason='DbUpsert', message=f"Parameter `{name}` has been updated")

def create_user_entity(body, cursor, name : str):
    cursor.execute("SELECT entity_id FROM public.guacamole_entity where name = %s", [ name ])
    entity_id = cursor.fetchone()
    if not entity_id:
        cursor.execute("INSERT INTO public.guacamole_entity (name, type) VALUES (%s, 'USER');", [name])
        cursor.execute("SELECT entity_id FROM public.guacamole_entity where name = %s", [name])
        entity_id = cursor.fetchone()
        kopf.info(body, reason='DbUpsert', message=f"Entity `{name}` has been created")
    return entity_id[0]

def create_user(body, cursor, user_entity_id : int):
    password_hash_base64 = "a42b83d79d300dbcd585c8d8f12564d3c5951578d057879c428bc553d84b7ede"
    password_salt_base64 = "e52dc1ea654a674ece9232116bba5bb4f8aed12baeb797d09109807d63f9027b"
    password_hash = base64.decodebytes(password_hash_base64.encode("ascii"))
    password_salt = base64.decodebytes(password_salt_base64.encode("ascii"))
    cursor.execute("SELECT user_id FROM public.guacamole_user where entity_id = %s", [ user_entity_id ])
    user_id = cursor.fetchone()
    if not user_id:
        cursor.execute("INSERT INTO public.guacamole_user (entity_id, disabled, expired, password_hash, password_salt, password_date) VALUES (%s, false, false, %s, %s, %s);", [user_entity_id, password_hash, password_salt, datetime.datetime.now()])
        cursor.execute("SELECT user_id FROM public.guacamole_user where entity_id = %s", [user_entity_id])
        user_id = cursor.fetchone()
        kopf.info(body, reason='DbUpsert', message=f"User `{user_id}` has been created")
    return user_id[0]

def set_connection_permission(body, cursor, user_id : int, connection_id : int, permission : str = "READ"):
    cursor.execute("SELECT \"permission\" FROM public.guacamole_connection_permission WHERE connection_id = %s and entity_id = %s;", [connection_id, user_id])
    current_permission = cursor.fetchone()
    if not current_permission:
        cursor.execute("INSERT INTO public.guacamole_connection_permission (connection_id, entity_id, \"permission\") VALUES (%s, %s, %s);", [connection_id, user_id, permission])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on connection {connection_id}")
    elif current_permission[0] != permission:
        cursor.execute("UPDATE public.guacamole_connection_permission SET \"permission\" = %s WHERE connection_id = %s and entity_id = %s);", [permission, connection_id, user_id])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on connection {connection_id}")


def set_connection_group_permission(body, cursor, user_id : int, connection_group_id : int, permission : str = "READ"):
    cursor.execute("SELECT \"permission\" FROM public.guacamole_connection_group_permission WHERE connection_group_id = %s and entity_id = %s;", [connection_group_id, user_id])
    current_permission = cursor.fetchone()
    if not current_permission:
        cursor.execute("INSERT INTO public.guacamole_connection_group_permission (connection_group_id, entity_id, \"permission\") VALUES (%s, %s, %s);", [connection_group_id, user_id, permission])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on connection group {connection_group_id}")
    elif current_permission[0] != permission:
        cursor.execute("UPDATE public.guacamole_connection_group_permission SET \"permission\" = %s WHERE connection_group_id = %s and entity_id = %s);", [permission, connection_group_id, user_id])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on connection group {connection_group_id}")


def set_user_permission(body, cursor, user_id : int, entity_id : int, permission : str = "READ"):
    cursor.execute("SELECT \"permission\" FROM public.guacamole_user_permission WHERE affected_user_id = %s and entity_id = %s;", [user_id, entity_id])
    current_permission = cursor.fetchone()
    if not current_permission:
        cursor.execute("INSERT INTO public.guacamole_user_permission (affected_user_id, entity_id, \"permission\") VALUES (%s, %s, %s);", [user_id, entity_id, permission])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on entity {entity_id}")
    elif current_permission[0] != permission:
        cursor.execute("UPDATE public.guacamole_user_permission SET \"permission\" = %s WHERE affected_user_id = %s and entity_id = %s);", [permission, user_id, entity_id])
        kopf.info(body, reason='DbUpsert', message=f"User {user_id} has been assigned {permission} on entity {entity_id}")

def create_service_object(service_name, deployment_name, username, workspace):
    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name, 
            annotations={"xlscsde.nhs.uk/workspace" : workspace, "xlscsde.nhs.uk/username" : username},
            labels={
                "xlscsde.nhs.uk/purpose" : "workspace-client"
            }    
        ),
        spec=client.V1ServiceSpec(
            selector={"xlscsde.nhs.uk/deployment-name": deployment_name},
            cluster_ip="None",
            type="ClusterIP",
            ports=[client.V1ServicePort(
                port=5900,
                target_port=5900
            )]
        )
    )


def create_deployment_object(deployment_name, username, workspace, replicas):
    # Configureate Pod template container
    container = client.V1Container(
        name=deployment_name,
        image=os.environ.get("IMAGE_NAME"),
        ports=[client.V1ContainerPort(container_port=5900)],
        volume_mounts=[
            client.V1VolumeMount(
                name="guacamole-certificates",
                mount_path="/usr/lib/firefox/distribution/certs",
                read_only=True
            ),
            client.V1VolumeMount(
                name="firefox-config",
                mount_path="/usr/lib/firefox/distribution",
                read_only=True
            ),
        ]
    )

    # Create and configure a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(
            labels={
                "xlscsde.nhs.uk/deployment-name": deployment_name
            }, 
            annotations={
                "xlscsde.nhs.uk/workspace" : workspace, 
                "xlscsde.nhs.uk/username" : username
            }),
        spec=client.V1PodSpec(
            containers=[container],
            volumes=[
                client.V1Volume(
                    name="guacamole-certificates",
                    config_map=client.V1ConfigMapVolumeSource(
                        name="xlscsde-enterprise-certificate"
                    )
                ),
                client.V1Volume(
                    name="firefox-config",
                    config_map=client.V1ConfigMapVolumeSource(
                        name="firefox-config"
                    )
                ),
            ]
            ),
    )

    # Create the specification of deployment
    spec = client.V1DeploymentSpec(
        replicas=replicas, template=template, selector={
            "matchLabels":
            {"xlscsde.nhs.uk/deployment-name": deployment_name}})

    # Instantiate the deployment object
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(
            name=deployment_name,
            labels={
                "xlscsde.nhs.uk/purpose" : "workspace-client"
            }    
        ),
        spec=spec,
    )

    return deployment

def check_deployment_exists(deployment_name, namespace):
    try:
        apps_v1.read_namespaced_deployment(name=deployment_name,namespace=namespace)
        return True
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise e
        
        return False

def check_service_exists(deployment_name, namespace):
    try:
        core_api.read_namespaced_service(name=deployment_name,namespace=namespace)
        return True
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise e
        
        return False

def apply_deployment(deployment_name, username, workspace, replicas):
    deployment = create_deployment_object(deployment_name, username, workspace, replicas)
    namespace = os.environ.get("NAMESPACE", "guacamole")

    if not check_deployment_exists(deployment_name, namespace):
        resp = apps_v1.create_namespaced_deployment(
            body=deployment, namespace=namespace
        )
    else:
        resp = apps_v1.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace, body=deployment
        )
    

def apply_service(deployment_name, username, workspace):
    service_name = f"client-{deployment_name}"
    service = create_service_object(service_name, deployment_name, username, workspace)
    namespace = os.environ.get("NAMESPACE", "guacamole")

    if not check_service_exists(service_name, namespace):
        resp = core_api.create_namespaced_service(
            body=service, namespace=namespace
        )
    else:
        resp = core_api.patch_namespaced_service(
            name=service_name, namespace=namespace, body=service
        )
    


def get_status(body):
    return body.get("status", {}).get("statusText", status_provisioning)

def get_workspace(body):
    return body.get("spec", {}).get("workspace")

def get_replicas(body):
    return body.get("spec", {}).get("replicas", 0)

def get_username(body):
    return body.get("spec", {}).get("username")

def get_deployment_name(body):
    workspace = get_workspace(body)
    username = get_username(body)
    default_value = uuid5(NAMESPACE_URL, f"https://workspaces.xlscsde.nhs.uk/{parse.quote(workspace)}/{parse.quote(username)}").hex
    return body.get("status", {}).get("deploymentName", default_value)

def get_name(body):
    return body.get("metadata", {}).get("name")

def get_namespace(body):
    return body.get("metadata", {}).get("namespace")


def patch_deployment_name(body, deployment_name : str):
    patch_body = {
        "status" : {
            "deploymentName" : deployment_name
        }
    }

    current_deployment_name = body.get("status", {}).get("deploymentName", "")

    if current_deployment_name != deployment_name:
        patched_object = custom_objects_api.patch_namespaced_custom_object_status(
            group=group, 
            version=version, 
            body=patch_body, 
            plural=plural,
            name=get_name(body), 
            namespace=get_namespace(body))
        return patched_object
    else:
        return body

def patch_status(body, new_status : str):
    patch_body = {
        "status" : {
            "statusText" : new_status
        }
    }
    current_status = get_status(body)
    patched_object = custom_objects_api.patch_namespaced_custom_object_status(
        group=group, 
        version=version, 
        body=patch_body, 
        plural=plural,
        name=get_name(body), 
        namespace=get_namespace(body))
    kopf.info(body, reason='StateUpdated', message=f"Status updated to {new_status} FROM {current_status}")
    return patched_object

@kopf.on.create(group=group, kind=kind)
@kopf.on.update(group=group, kind=kind)
@kopf.on.resume(group=group, kind=kind)
async def binding_updated(body, **_):
    namespace = os.environ.get("NAMESPACE", "guacamole")
    workspace = get_workspace(body)
    username = get_username(body)
    deployment_name = get_deployment_name(body)
    body = patch_deployment_name(body, deployment_name)

    status_text = get_status(body)
    conn = psycopg2.connect(
        database=os.environ.get("DB_NAME"),
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        port=os.environ.get("DB_PORT")
        )
    cursor = conn.cursor()
    connection_group_id = create_connection_group(body, cursor, workspace)
    connection_id = create_connection(body, cursor, connection_group_id, username)
    user_entity_id = create_user_entity(body, cursor, f"{workspace}@{username}")
    user_id = create_user(body, cursor, user_entity_id)
    set_user_permission(body, cursor, user_id, user_entity_id)
    set_connection_group_permission(body, cursor, user_entity_id, connection_group_id)
    set_connection_parameter(body, cursor, connection_id, "disable-copy", "true")
    set_connection_parameter(body, cursor, connection_id, "disable-paste", "true")
    set_connection_parameter(body, cursor, connection_id, "hostname", f"client-{deployment_name}.{namespace}.svc.cluster.local")
    set_connection_parameter(body, cursor, connection_id, "password", "1234")
    set_connection_parameter(body, cursor, connection_id, "port", "5900")
    
    replicas = get_replicas(body)

    apply_deployment(deployment_name, username, workspace, replicas)
    apply_service(deployment_name, username, workspace)
    set_connection_permission(body, cursor, user_entity_id, connection_id)

    if status_text == status_provisioning:
        patched_body = patch_status(body, status_ready)
        print(f"Status updated: {patched_body}")

    conn.commit()
    conn.close()    
