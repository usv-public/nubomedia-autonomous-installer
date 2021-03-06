# Copyright 2016 Universitatea Stefan cel Mare Suceava www.usv.ro
# Copyright 2016 NUBOMEDIA www.nubomedia.eu
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from keystoneclient.v2_0 import client as keystoneClient
from glanceclient import Client as glanceClient
from keystoneclient import session as keystoneSession
from novaclient import client as novaClient
from cinderclient import client as cinderClient
from contextlib import contextmanager
from credentials import *
import paramiko
import time
import os
import tempfile
import logging
import sys
import urllib2
import requests
from cmd import Cmd

class StreamToLogger(object):
   """
   Fake file-like stream object that redirects writes to a logger instance.
   """
   def __init__(self, logger, log_level=logging.INFO):
      self.logger = logger
      self.log_level = log_level
      self.linebuf = ''

   def write(self, buf):
      for line in buf.rstrip().splitlines():
         self.logger.log(self.log_level, line.rstrip())

logging.basicConfig(
   level=logging.DEBUG,
   format='%(asctime)s:%(levelname)s:%(name)s:%(message)s',
   filename="installer.log",
   filemode='a'
)

if enabled_logging:
    stdout_logger = logging.getLogger('STDOUT')
    sl = StreamToLogger(stdout_logger, logging.WARNING)
    sys.stdout = sl

    stderr_logger = logging.getLogger('STDERR')
    sl = StreamToLogger(stderr_logger, logging.ERROR)
    sys.stderr = sl

class KeystoneManager(object):
    def __init__(self, **kwargs):
        """Get an endpoint and auth token from Keystone.
        :param username: name of user param password: user's password
        :param tenant_id: unique identifier of tenant
        :param tenant_name: name of tenant
        :param auth_url: endpoint to authenticate against
        :param token: token to use instead of username/password
        """
        kc_args = {}

        if kwargs.get('endpoint'):
            kc_args['endpoint'] = kwargs.get('auth_url')
        else:
            kc_args['auth_url'] = kwargs.get('auth_url')

        if kwargs.get('tenant_id'):
            kc_args['tenant_id'] = kwargs.get('tenant_id')
        else:
            kc_args['tenant_name'] = kwargs.get('tenant_name')

        if kwargs.get('token'):
            kc_args['token'] = kwargs.get('token')
        else:
            kc_args['username'] = kwargs.get('username')
            kc_args['password'] = kwargs.get('password')

        print kc_args

        self.ksclient = keystoneClient.Client(**kc_args)
        self.session = keystoneSession.Session(auth=self.ksclient)
        self.token = self.ksclient.auth_token
        self.tenant_id = self.ksclient.project_id
        self.tenant_name = self.ksclient.tenant_name
        self.username = self.ksclient.username
        self.password = self.ksclient.password
        self.project_id = self.ksclient.project_id
        self.auth_url = self.ksclient.auth_url

    def get_session(self):
        if self.session is None:
            self.session = keystoneSession.Session(auth=self.ksclient)
        return self.session

    def get_endpoint(self):
        if self.auth_url is None:
            self.auth_url = self.ksclient.auth_url
        return self.auth_url

    def get_token(self):
        if self.token is None:
            self.token = self.ksclient.auth_token
        return self.token

    def get_tenant_id(self):
        if self.tenant_id is None:
            self.tenant_id = self.ksclient.project_id
        return self.tenant_id

    def get_tenant_name(self):
        if self.tenant_name is None:
            self.tenant_name = self.ksclient.tenant_name
        return self.tenant_name

    def get_username(self):
        if self.username is None:
            self.username = self.ksclient.username
        return self.username

    def get_password(self):
        if self.password is None:
            self.password = self.ksclient.password
        return self.password

    def get_project_id(self):
        if self.project_id is None:
            self.project_id = self.ksclient.project_id
        return self.project_id


class NovaManager(object):
    def __init__(self, **kwargs):
        self.nova = novaClient.Client("2", **kwargs)
        self.docker_hypervisors = []

    def get_flavors(self):
        print self.nova.flavors.list()
        return self.nova.flavors.list()

    def get_hypervisors_number(self):
        x = self.nova.hypervisors.list()
        print "Number of hypervisors :", len(x)
        return len(x)

    def get_hypervisor_ip(self,id):
        return getattr(self.nova.hypervisors.get(id), "host_ip")

    def get_hypervisor_type(self,id):
        return getattr(self.nova.hypervisors.get(id), "hypervisor_type")

    def get_docker_hypervisors_ip(self):
        for x in range(1, novaManager.get_hypervisors_number()):
            if novaManager.get_hypervisor_type(x) == 'docker':
                self.docker_hypervisors.append(novaManager.get_hypervisor_ip(x))
        return self.docker_hypervisors

    def create_floating_ip(self):
        unused_floating_ips = 0
        y = None
        floating_ips_list = self.nova.floating_ips.list()
        for i in floating_ips_list:
            x = getattr(i, "fixed_ip")
            if x is None:
                unused_floating_ips += 1
        if unused_floating_ips == 0:
            y = self.nova.floating_ips.create(get_env_vars()['floating_ip_pool'])
            print y
        return y

    def associate_floating_ip(self, instance_id):
        floating_ips_list = self.nova.floating_ips.list()
        fip = None
        for i in floating_ips_list:
            x = getattr(i, "fixed_ip")
            if x is None:
                fip = getattr(i, "ip")
                self.nova.servers.find(id=instance_id).add_floating_ip(fip)
                return fip
            else:
                fip = self.nova.floating_ips.create(get_env_vars()['floating_ip_pool'])
                self.nova.servers.find(id=instance_id).add_floating_ip(fip)
                return fip.ip
        return fip

    def start_kvm_instance(self, instance_name, image_id, flavor, private_key, user_data):
        boot_start_time = time.time()
        instance = self.nova.servers.create(instance_name,
            image_id,
            flavor,
            meta=None,
            files=None,
            reservation_id=None,
            min_count=None,
            max_count=None,
            security_groups=None,
            userdata=user_data,
            key_name=private_key,
            availability_zone=None,
            block_device_mapping=None,
            block_device_mapping_v2=None,
            nics=None,
            scheduler_hints=None,
            config_drive=None,
            disk_config=None)
        print "Instance name is %s and instance id is %s" % (instance.name, instance.id)
        status = "PENDING"
        while status != "ACTIVE":
            instances = self.nova.servers.list()
            for instance_temp in instances:
                if instance_temp.id == instance.id:
                    status = instance_temp.status
            print "Instance %s status is %s" % (instance_name, status)
            time.sleep(10)
        boot_time = time.time() - boot_start_time
        print "Instance %s has been booted in %s seconds" % (instance_name, boot_time)
        return instance.id

    def get_flavor_id(self, flavor_name):
        flavors = self.nova.flavors.list()
        for i in flavors:
            x = getattr(i,"name")
            if x == flavor_name:
                flavorid = getattr(i, "id")
        print "Flavor %s with id %s" % (flavor_name, flavorid)
        return flavorid

    def get_security_group_id(self, security_group):
        sec_groups = self.nova.security_groups.list()
        for i in sec_groups:
            x = getattr(i, "name")
            if x == security_group:
                sec_group_id = getattr(i, "id")
        print "Security group %s with id %s " % (security_group, sec_group_id)
        return sec_group_id

class GlanceManager(object):
    def __init__(self, **kwargs):
        kc_args = {}

        if kwargs.get('endpoint'):
            kc_args['endpoint'] = kwargs.get('endpoint')

        if kwargs.get('token'):
            kc_args['token'] = kwargs.get('token')

        print kc_args

        self.glclient = glanceClient('1', **kc_args)
        self.glclient2 = glanceClient('2', **kc_args)
        self.dockerimages = []

    def get_docker_images(self):
        imagelist = self.glclient.images.list()
        for i in imagelist:
            x = getattr(i,"container_format")
            if x == 'docker':
                imagename = getattr(i,"name")
                self.dockerimages.append(imagename)
        return self.dockerimages

    def upload_qemu_image(self, image_name, image_location, *image_description):
        upload_start_time = time.time()
        image = self.glclient.images.create(name=image_name, container_format='bare', disk_format='qcow2')
        print image.status
        image.update(data=open(image_location, 'rb'))
        try:
            image_description
        except NameError:
            None
        else:
            image.update(properties=dict(description=image_description))
        with open(image_location, 'wb') as f:
            for chunk in image.data():
                f.write(chunk)
        img_upload_time = time.time() - upload_start_time
        print "Image %s has been uploaded in %s seconds." % (image_name, img_upload_time)
        return image.status

    def upload_remote_image(self, image_name, image_location, *image_description):
        upload_start_time = time.time()
        image = self.glclient.images.create(disk_format='qcow2', container_format='bare', name=image_name,
                                            copy_from=image_location)
        status = "queued"
        while status != "active":
            images = self.glclient.images.list()
            for images_temp in images:
                if images_temp.id == image.id:
                    status = images_temp.status
            print "Image %s status is %s" % (image_name, status)
            time.sleep(10)
        img_upload_time = time.time() - upload_start_time
        print "Image %s has been uploaded in %s seconds." % (image_name, img_upload_time)
        return image.status

    def upload_docker_image(self, docker_img_name, *docker_image_description):
        upload_start_time = time.time()
        image = self.glclient.images.create(name=docker_img_name, container_format='docker', disk_format='raw')
        print image.status
        image.update(data=open('/dev/null', 'rb'))
        try:
            docker_image_description
        except NameError:
            None
        else:
            image.update(properties=dict(description=docker_image_description))
        with open('/dev/null', 'wb') as f:
            for chunk in image.data():
                f.write(chunk)
        img_upload_time = time.time() - upload_start_time
        print "Image %s has been uploaded in %s seconds." % (docker_img_name, img_upload_time)
        return image.status

    def get_image_id(self, image_name):
        imagelist = self.glclient.images.list()
        for i in imagelist:
            x = getattr(i,"name")
            if x == image_name:
                imageid = getattr(i, "id")
        print "Image name %s" % imageid
        return imageid


class CinderManager(object):
    def __init__(self, **kwargs):
        self.cinder = cinderClient.Client("1", **kwargs)

    def get_volumes_list(self):
        print self.cinder.volumes.list()
        return self.cinder.volumes.list()

    def create_volume(self, name, size):
        myvol = self.cinder.volumes.create(display_name=name, size=int(size))
        return myvol

    def attach_volume(self, volume, instance_id, path):
        attach = volume.attach(instance_id, path)
        return attach

class OpenStackManager(object):
    def __init__(self, **kwargs):
        print None

    def pull_docker_images(self):
        # Pull all docker images on all docker compute nodes, requires OpenStack admin user
        if get_keystone_creds()['username'] == 'admin':
            dockerIPs = novaManager.get_docker_hypervisors_ip()
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print get_master_creds()
            ssh.connect(get_master_ip(), **get_master_creds())
            for i in dockerIPs:
                print 'Docker hypervisor IP address:', i
                for j in dockerimages:
                    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command("ssh %s 'docker pull %s'" % (i, j))
                    print ssh_stdout.readlines()
            ssh.close()
        return None


class NubomediaManager(object):
    def __init__(self, **kwargs):
        print None

    def download_images(self, remote_location, local_location):
        url = remote_location

        # file_name = url.split('/')[-1]
        file_name = local_location

        u = urllib2.urlopen(url)
        f = open(file_name, 'wb')
        meta = u.info()
        file_size = int(meta.getheaders("Content-Length")[0])
        print "Downloading: %s Bytes: %s" % (file_name, file_size)

        file_size_dl = 0
        block_sz = 8192
        while True:
            buffer = u.read(block_sz)
            if not buffer:
                break

            file_size_dl += len(buffer)
            f.write(buffer)
            status = r"%10d  [%3.2f%%]" % (file_size_dl, file_size_dl * 100. / file_size)
            status = status + chr(8)*(len(status)+1)
            print status,

        f.close()
        return None

    def upload_file(self, instance_ip, instance_user, instance_key, file_data, remote_filename, remote_path):
        # Upload file

        d = {}
        d['username'] = instance_user
        d['pkey'] = paramiko.RSAKey.from_private_key_file(instance_key)

        transport = paramiko.Transport(instance_ip, '22')
        transport.connect(**d)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            sftp.chdir(remote_path)  # Test if remote_path exists
        except IOError:
            sftp.mkdir(remote_path)  # Create remote_path
            sftp.chdir(remote_path)
        print sftp.listdir()
        sftp.put(file_data, remote_filename)
        sftp.close()
        return None

    def run_user_data(self, instance_ip, instance_user, instance_key, user_data):
        # Upload user_data
        remote_path = "/tmp/"

        d = {}
        d['username'] = instance_user
        d['pkey'] = paramiko.RSAKey.from_private_key_file(instance_key)

        transport = paramiko.Transport(instance_ip, '22')
        transport.connect(**d)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            sftp.chdir(remote_path)  # Test if remote_path exists
        except IOError:
            sftp.mkdir(remote_path)  # Create remote_path
            sftp.chdir(remote_path)
        print sftp.listdir()

        @contextmanager
        def tempinput(data):
            temp = tempfile.NamedTemporaryFile(delete=False)
            temp.write(data)
            temp.close()
            yield temp.name
            os.unlink(temp.name)
        with tempinput(user_data) as tempfilename:
            sftp.put(tempfilename, 'nubomedia_run_script.sh')
        sftp.close()

        # Run user_data
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(instance_ip, **d)
        ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command("sudo -- sh -c 'chmod +x /tmp/nubomedia_run_script.sh && "
                                                             "cd /tmp && ./nubomedia_run_script.sh'")
        print ssh_stdout.readlines()
        return None


def autoinstall():

    # Connect to Keystone
    kwargs = {}
    kwargs = get_keystone_creds()
    keystoneManager = KeystoneManager(**kwargs)

    # Get the list of the docker images names
    kwargs = {}
    kwargs['token'] = keystoneManager.get_token()
    kwargs['endpoint'] = get_glance_creds()
    glanceManager = GlanceManager(**kwargs)
    dockerimages = glanceManager.get_docker_images()

    # Connect to Nova
    kwargs = get_nova_creds()
    novaManager = NovaManager(**kwargs)

    openStackManager = OpenStackManager()
    nubomediaManager = NubomediaManager()

    # Connect to Cinder and create disk
    cinderManager = CinderManager(**kwargs)
    cinderManager.get_volumes_list()
    # monitoring_disk = cinderManager.create_volume("monitoring_disk", 10)

    # Create a floating IP if there is no floating IP on that tenant
    print novaManager.create_floating_ip()

    ##############################
    # Start NUBOMEDIA deployment
    ##############################

    start_time = time.time()
    print 'Starting NUBOMEDIA deployment'

    ####################################
    # Download NUBOMEDIA Images locally
    ####################################

    if download_images:
        # Download Monitoring Image locally
        nubomediaManager.download_images(monitoring_remote_img, monitoring_qemu_img)

        # Download Kurento Media Server Image locally
        nubomediaManager.download_images(kms_remote_img, kms_qemu_img)

        # Download NUBOMEDIA Controller locally
        nubomediaManager.download_images(controller_remote_img, controller_qemu_img)

        # Download TURN Server locally
        nubomediaManager.download_images(turn_remote_img, turn_qemu_img)

        # Download Cloud Repository locally
        nubomediaManager.download_images(cloud_repository_remote_img, cloud_repository_qemu_img)

        # Download NUBOMEDIA Repository locally
        nubomediaManager.download_images(repository_remote_img, repository_qemu_img)

    ####################################
    # Upload NUBOMEDIA Images if needed
    ####################################
    kms_image = kms_image_name
    if upload_images:
        # Upload Kurento Media Server on KVM or Docker depending on what you've chosen on the variables.py file
        if not use_kurento_on_docker:
            glanceManager.upload_docker_image(kms_image_name, kms_image_description)
            kms_image = kms_image_name
        else:
            glanceManager.upload_docker_image(kms_docker_img, kms_docker_image_description)
            kms_image = kms_docker_img

        # Upload Monitoring machine Image on Glance
        glanceManager.upload_remote_image(monitoring_image_name, monitoring_remote_img, monitoring_image_description)

        # Upload TURN Server Image on Glance
        glanceManager.upload_remote_image(turn_image_name, turn_remote_img, turn_image_description)

        # Upload Cloud Repository Image on Glance
        glanceManager.upload_remote_image(cloud_repository_image_name,
                                          cloud_repository_remote_img,
                                          cloud_repository_image_description)

        # Upload Controller Image on Glance
        glanceManager.upload_remote_image(controller_image_name, controller_remote_img, controller_image_description)

    # Log time needed to upload NUBOMEDIA Images
    upload_time = time.time() - start_time
    print "Time needed for uploading of the NUBOMEDIA images was %s seconds " % upload_time
    upload_time = time.time()

    #######################################
    # Start NUBOMEDIA platform instances
    #######################################

    # Start Monitoring instance
    instance_monitoring = novaManager.start_kvm_instance(monitoring_image_name,
                                                         glanceManager.get_image_id(monitoring_image_name),
                                                         novaManager.get_flavor_id(monitoring_flavor),
                                                         private_key,
                                                         '')
    instance_monitoring_ip = novaManager.associate_floating_ip(instance_monitoring)
    print "Monitoring instance name=%s , id=%s , public_ip=%s" % (monitoring_image_name,
                                                                  instance_monitoring,
                                                                  instance_monitoring_ip)

    # Start TURN Server instance
    instance_turn = novaManager.start_kvm_instance(turn_image_name,
                                                   glanceManager.get_image_id(turn_image_name),
                                                   novaManager.get_flavor_id(turn_flavor),
                                                   private_key,
                                                   turn_user_data)
    instance_turn_ip = novaManager.associate_floating_ip(instance_turn)
    print "TURN instance name=%s , id=%s , public_ip=%s" % (turn_image_name,
                                                            instance_turn,
                                                            instance_turn_ip)

    # Start Controller instance
    instance_controller = novaManager.start_kvm_instance(controller_image_name,
                                                         glanceManager.get_image_id(controller_image_name),
                                                         novaManager.get_flavor_id(controller_flavor),
                                                         private_key,
                                                         '')
    instance_controller_ip = novaManager.associate_floating_ip(instance_controller)
    print "Controller instance name=%s , id=%s , public_ip=%s" % (controller_image_name,
                                                                  instance_controller,
                                                                  instance_controller_ip)

    # Log time needed to boot NUBOMEDIA instances

    boot_time = time.time() - upload_time
    print "Time needed to start the NUBOMEDIA instances was %s seconds " % boot_time
    boot_time = time.time()

    ##########################################
    # Configure  NUBOMEDIA platform services
    ##########################################

    # Added a delay before running the configuration scripts on the instances in order to allow them to be
    # properly provisioned and booted
    time.sleep(240)

    # cinderManager.attach_volume(monitoring_disk, instance_monitoring, '/dev/vdb')

    # Delay for allowing the volume to get attached to the monitoring instance
    time.sleep(60)
    # Configure the Monitoring instance
    nubomediaManager.run_user_data(instance_monitoring_ip, "ubuntu", private_key, monitoring_user_data)

    # Configure the TURN server instance
    nubomediaManager.run_user_data(instance_turn_ip, "ubuntu", private_key, turn_user_data)

    # Configuring the Controller instance
    # Upload the OpenShift Keystore first
    nubomediaManager.upload_file(instance_controller_ip,
                                 'ubuntu',
                                 private_key,
                                 openshift_keystore,
                                 'openshift_keystore',
                                 '/tmp/')

    # Configure the NUBOMEDIA controller
    nubomediaManager.run_user_data(instance_controller_ip, "ubuntu", private_key,
                                   controller_user_data % (openshift_ip,
                                                           openshift_domain,
                                                           iaas_ip,
                                                           username,
                                                           password,
                                                           tenant_name,
                                                           private_key,
                                                           nubomedia_admin_paas,
                                                           instance_monitoring_ip,
                                                           instance_turn_ip,
                                                           instance_turn_ip,
                                                           kms_image))

    # Log time needed to boot NUBOMEDIA instances
    cfg_time = time.time() - boot_time
    print "Time needed to configure the NUBOMEDIA platform was %s seconds " % cfg_time

    elapsed_time = time.time() - start_time
    print "Total time needed for deployment of the NUBOMEDIA platform was %s seconds " % elapsed_time

def manualinstall():
    iaas_ip = raw_input("Please input the IaaS public IP address : ")
    auth_url = "http://%s:5000/v2.0" % iaas_ip
    username = raw_input("Please input the IaaS admin username : ")
    password = raw_input("Please input the IaaS admin password : ")
    tenant_name = raw_input("Please input the IaaS Tenant name : ")
    floating_ip_pool = raw_input("Please input the floating IP pool that must be used for this tenant : ")
    private_key = raw_input("Please input the public key name that can be used in this tenant : ")

    # Glance
    glance_endpoint = "http://%s:9292" % iaas_ip

    # Master SSH credentials
    master_ip = "%s" % iaas_ip
    master_user = raw_input("Please input the IaaS ssh username : ")
    master_pass = raw_input("Please input the IaaS ssh password : ")
    print "test%stest" % master_pass
    if master_pass == "":
        master_key = 'hypervisor_id_rsa'

    # Other variables

    openshift_ip = raw_input("Please input the OpenShift IP address : ")
    print "OpenShift Keystore should be generated using the Portacle tool from http://portecle.sourceforge.net/ an" \
          " added to the root of the repository with the following name: openshift-keystore"
    openshift_domain = raw_input("Please input the wildcard domain to be used for applications inside OpenShift : ")



class InstallerCommandPrompt(Cmd):

    def do_auto_install(self, args):
        """Starts the NUBOMEDIA Autonomous Installer using the configuration available on variables.py file."""
        print "NUBOMEDIA Platform as a Service installation has been started. Be sure you've configured everything " \
              "in the variables.py file."
        autoinstall()

    def do_manual_install(self, args):
        """
        Starts the manual installation of the NUBOMEDIA Platform as a Service.
        You will be prompted to input configuration information like OpenStack and OpenShift credentials,
        mysql passwords, etc."""
        print "Manual Installation of the NUBOMEDIA Platform as a Service has been started."
        manualinstall()

    def do_quit(self, args):
        """Quits the program."""
        print "Quitting."
        raise SystemExit


if __name__ == '__main__':

    prompt = InstallerCommandPrompt()
    prompt.prompt = '> '
    prompt.cmdloop('Starting prompt of NUBOMEDIA Autonomous installer...')

    # Exit
    sys.exit(0)







