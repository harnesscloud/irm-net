# IRM-Net 

## Dependencies

### pip packages

- Flask
- flask-classy
- requests

### GitLab project

- Gabriel Figueiredo/harness-resource-manager

(cloned in the same level directory as IRM-Net)

---- irm-net
|
+--- harness-resource-manager

## Transport Control rules

IRM-NET installs traffic control rules on instantiated containers using ``tc``.
Since containers do not have necessarily a floating IP, IRM-NET starts an ssh session with ``conpaas-director``,
which always has a floating IP.
In its turn, ``conpaas-worker`` installs the traffic control rules on the appropriate containers.

Limitations: this mechanism currently assumes that each compute node does not host more than one container.
