# Jenkins controller with Docker CLI, kubectl and the plugins this pipeline needs.
FROM jenkins/jenkins:lts-jdk21

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# kubectl is only needed for the optional Minikube stage. If dl.k8s.io is slow or
# unreachable, skip it instead of failing the whole Jenkins build.
RUN (KUBECTL_VERSION="$(curl -fsSL --connect-timeout 10 --max-time 20 https://dl.k8s.io/release/stable.txt)" \
  && curl -fsSLo /usr/local/bin/kubectl --connect-timeout 10 --max-time 120 \
       "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/$(dpkg --print-architecture)/kubectl" \
  && chmod +x /usr/local/bin/kubectl) \
 || (rm -f /usr/local/bin/kubectl; echo "kubectl skipped: dl.k8s.io unreachable (only the optional Kubernetes stage needs it)")

USER jenkins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Skip the setup wizard: admin user, credentials and the job come from casc.yaml.
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false" \
    CASC_JENKINS_CONFIG=/var/jenkins_conf/casc.yaml
