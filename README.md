<p align="center">
  <a href="https://www.deepset.ai/haystack/"><img src="https://raw.githubusercontent.com/deepset-ai/haystack/main/docs/img/haystack_logo_colored.png" alt="Haystack"></a>
</p>

**Main Components**

- Elastic Search document store dimension 384
- Multihop Embedding Retriever (dense)
- Seq2Seq Generator for LFQA (long form question answering)
- Streamlit web app for UI for Q&A (questions and answers)

**Full Installation**

If you plan to be using more advanced features like Milvus, FAISS, Weaviate, OCR or Ray,
you will need to install a full version of Haystack.
The following command will install the latest version of Haystack from the main branch.

```
git clone https://github.com/deepset-ai/haystack.git
cd haystack
pip install --upgrade pip
pip install -e '.[all]' ## or 'all-gpu' for the GPU-enabled dependencies
```

If you cannot upgrade `pip` to version 21.3 or higher, you will need to replace:
- `'.[all]'` with `'.[sql,only-faiss,only-milvus1,weaviate,graphdb,crawler,preprocessing,ocr,onnx,ray,dev]'`
- `'.[all-gpu]'` with `'.[sql,only-faiss-gpu,only-milvus1,weaviate,graphdb,crawler,preprocessing,ocr,onnx-gpu,ray,dev]'`

For an complete list of the dependency groups available, have a look at the `haystack/pyproject.toml` file.

To install the REST API and UI, run the following from the root directory of the Haystack repo

```
pip install rest_api/
pip install ui/
```
**Local**

Start up a Haystack service via [Docker Compose](https://docs.docker.com/compose/).
With this you can begin calling it directly via the REST API or even interact with it using the included Streamlit UI.

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

**Note**: The following containers are started as a part of this demo:

* Haystack API: listens on port 8000
* DocumentStore (Elasticsearch): listens on port 9200
* Streamlit UI: listens on port 8501
