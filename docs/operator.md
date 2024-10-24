---
title: AWMS Guacamole Operator
layout: page
parent: Components
---


The [AWMS](https://lsc-sde.github.io/lsc-sde/AWMS.html) Guacamole Operator is a component of the [External Access Capabilities](https://lsc-sde.github.io/lsc-sde/External-Access.html) of the solution.

# What does this component do?
The AWMS Guacamole Operator watches all resources of type [AnalyticsWorkspaceBindings](https://lsc-sde.github.io/lsc-sde/AMWS/Custom-Resources/AnalyticsWorkspaceBindings.html). Upon any create or update to these bindings, the operator create and maintain the objects in kubernetes for an individual [browser container](https://lsc-sde.github.io/lsc-sde/External-Access/Browser-Container.html) to function, such as:
* Deployments relating to the individual browser container
* Services relating to the individual browser container.


It will also update the database for Apache Guacamole letting it know about:
* The User
* The browser containers connection
* The Mapping between these two items. 

# How does this component do it's task?
This component uses [KOPF](https://lsc-sde.github.io/lsc-sde/Developer-Guide/KOPF.html) to provide an operator model in kubernetes. 

When an create/update/resume action is received for an AnalyticsWorkspaceBinding object, it is created in kubernetes it:
* Calculates a deployment name for the object based upon the combination of the workspace and username supplied
* On the database for apache guacamole it will create a connection group, the connection itself, the user entity, and the user, as well as any permissions or parameters to support these items.
* On kubernetes it will then create a standardised deployment (initially scaled to 0 if the object is new) for the browser container to be created, as well as the service object to allow other containers to connect to it internally. 
* It will then patch the status of the resource 

# Component Details
## Permissions
The [AWMS](https://lsc-sde.github.io/lsc-sde/AWMS.html) Guacamole Operator has the following permissions:

| Api Group | Resource | Permissions |
| --- | --- | --- |
| | services | get, watch, list |
| | services/status | patch |
| | namespaces | get, watch, list |
| | events | create |
| apiextensions.k8s.io | customresourcedefinitions | get, watch, list |
| admissionregistration.k8s.io | validatingwebhookconfigurations | create, patch |
| xlscsde.nhs.uk | analyticsworkspacebindings | get, watch, list, patch |
| xlscsde.nhs.uk | analyticsworkspaces | get, watch, list, patch |
| xlscsde.nhs.uk | analyticsworkspacebindings/status | patch |
| xlscsde.nhs.uk | analyticsworkspacebindings/scale | patch |
| xlscsde.nhs.uk | analyticsworkspaces/status | patch |
| xlscsde.nhs.uk | analyticsworkspaces/scale | patch |
| kopf.dev | clusterkopfpeerings | list, watch, get, patch |