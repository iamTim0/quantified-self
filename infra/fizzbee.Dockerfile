# Fizzbee model checker.
#
# Fizzbee ships Linux and macOS binaries only -- there is no Windows build -- and
# the checker binary is linked against glibc 2.34+, which rules out older WSL
# distributions (Ubuntu 20.04 carries 2.31). Running it in a container gives every
# developer the same checker on any host, and matches what CI executes.
#
# Build:  docker build -f infra/fizzbee.Dockerfile -t qs-fizzbee .
# Run:    docker run --rm -v "$PWD:/work" qs-fizzbee specs/tenant_isolation.fizz
FROM ubuntu:25.10

# python3 is required by the Bazel-generated launcher that fronts the parser
# binary, even though the archive bundles its own interpreter for the parser
# itself. Without it the parse step dies with "env: 'python3': No such file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates python3 \
    && apt-get clean

ARG FIZZBEE_VERSION=v0.5.2

RUN curl -sfL -o /tmp/fizzbee.tar.gz \
      "https://github.com/fizzbee-io/fizzbee/releases/download/${FIZZBEE_VERSION}/fizzbee-${FIZZBEE_VERSION}-linux_x86.tar.gz" \
    && tar xzf /tmp/fizzbee.tar.gz -C /opt \
    && mv "/opt/fizzbee-${FIZZBEE_VERSION}-linux_x86" /opt/fizzbee \
    && rm /tmp/fizzbee.tar.gz

ENV PATH="/opt/fizzbee:${PATH}"
WORKDIR /work
ENTRYPOINT ["/opt/fizzbee/fizz"]
