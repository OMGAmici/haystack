<p align="center">
  <a href="https://www.deepset.ai/haystack/"><img src="https://raw.githubusercontent.com/deepset-ai/haystack/main/docs/img/haystack_logo_colored.png" alt="Haystack"></a>
</p>

<p>
    <a href="https://github.com/deepset-ai/haystack/actions/workflows/tests.yml">
        <img alt="Tests" src="https://github.com/deepset-ai/haystack/workflows/Tests/badge.svg?branch=main">
    </a>
    <a href="https://github.com/deepset-ai/haystack-json-schema/actions/workflows/schemas.yml">
        <img alt="Schemas" src="https://github.com/deepset-ai/haystack-json-schema/actions/workflows/schemas.yml/badge.svg">
    </a>
    <a href="https://docs.haystack.deepset.ai">
        <img alt="Documentation" src="https://img.shields.io/website?label=documentation&up_message=online&url=https%3A%2F%2Fdocs.haystack.deepset.ai">
    </a>
    <a href="https://github.com/deepset-ai/haystack/releases">
        <img alt="Release" src="https://img.shields.io/github/release/deepset-ai/haystack">
    </a>
    <a href="https://github.com/deepset-ai/haystack/commits/main">
        <img alt="Last commit" src="https://img.shields.io/github/last-commit/deepset-ai/haystack">
    </a>
    <a href="https://pepy.tech/project/farm-haystack">
        <img alt="Downloads" src="https://pepy.tech/badge/farm-haystack/month">
    </a>
    <a href="https://www.deepset.ai/jobs">
        <img alt="Jobs" src="https://img.shields.io/badge/Jobs-We're%20hiring-blue">
    </a>
        <a href="https://twitter.com/intent/follow?screen_name=deepset_ai">
        <img alt="Twitter" src="https://img.shields.io/twitter/follow/deepset_ai?style=social">
    </a>
</p>

## Main components:

- ES (ElasticSearch) document store of dimension 384
- Multihop Embedding Retriever
- Seq2Seq generator for LFQA (long form question answering)
- Streamlit app for simple UI

Follow our [introductory tutorial](https://haystack.deepset.ai/tutorials/first-qa-system)
to setup a question answering system using Python and start performing queries!
Explore [the rest of our tutorials](https://haystack.deepset.ai/tutorials)
to learn how to tweak pipelines, train models and perform evaluation.

## :beginner: Quick Demo

**Hosted**

Try out our hosted [Explore The World](https://haystack-demo.deepset.ai/) live demo here!
Ask any question on countries or capital cities and let Haystack return the answers to you.

**Local**

Start up a Haystack service via [Docker Compose](https://docs.docker.com/compose/).
With this you can begin calling it directly via the REST API or even interact with it using the included Streamlit UI.

<details>
  <summary>Click here for a step-by-step guide</summary>

**1. Update/install Docker and Docker Compose, then launch Docker**

```
    apt-get update && apt-get install docker && apt-get install docker-compose
    service docker start
```

**2. Clone Haystack repository**

```
    git clone https://github.com/deepset-ai/haystack.git
```

**3. Pull images & launch demo app**

```
    cd haystack
    docker-compose pull
    docker-compose up

    # Or on a GPU machine: docker-compose -f docker-compose-gpu.yml up
```

You should be able to see the following in your terminal window as part of the log output:

```
..
ui_1             |   You can now view your Streamlit app in your browser.
..
ui_1             |   External URL: http://192.168.108.218:8501
..
haystack-api_1   | [2021-01-01 10:21:58 +0000] [17] [INFO] Application startup complete.
```

**4. Open the Streamlit UI for Haystack by pointing your browser to the "External URL" from above.**

**Note**: The following containers are started:

* Haystack API: listens on port 8000
* DocumentStore (Elasticsearch): listens on port 9200
* Streamlit UI: listens on port 8501

Please note that the demo will [publish](https://docs.docker.com/config/containers/container-networking/) the container ports to the outside world. *We suggest that you review the firewall settings depending on your system setup and the security guidelines.*
