import os
import sys
import logging
from pathlib import Path
from json import JSONDecodeError

import pandas as pd
import streamlit as st
from annotated_text import annotation
from markdown import markdown

from ui.utils import (
    haystack_is_ready, 
    query,
    send_feedback, 
    upload_doc, 
    haystack_version, 
    get_backlink
)

def set_state_if_absent(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

def main():

    st.set_page_config(page_title="GURU AI demo", page_icon="https://haystack.deepset.ai/img/HaystackIcon.png")
    
    set_state_if_absent("question", None)
    set_state_if_absent("answer", None)
    set_state_if_absent("results", None)
    set_state_if_absent("raw_json", None)

    # Small callback to reset the interface in case the text of the question changes
    def reset_results(*args):
        st.session_state.answer = None
        st.session_state.results = None
        st.session_state.raw_json = None

    st.title("🧠 Question & Answers with GURU AI")

    st.markdown(
            """
    Based on the FAR pdf booklet, this demo will answer any questions you have about

    <h3 style='text-align:center;padding: 0 0 1rem;'> Federal Regulation Acquisition</h3>
   
    Ask any question and see if the AI can find the correct answer!

    *You can use keywords or full-fledged questions, and the AI will respond in complete sentences*
    """,
            unsafe_allow_html=True,
        )

    top_k_reader = 1
    top_k_retriever = 10
    st.sidebar.write("## File Upload:")
    data_files = st.sidebar.file_uploader("", type=["pdf"], accept_multiple_files=True)
    for data_file in data_files:
        # Upload file
        if data_file:
            raw_json = upload_doc(data_file)
            st.sidebar.write(str(data_file.name) + " &nbsp;&nbsp; ✅ ")
            st.subheader("REST API JSON response")
            st.sidebar.write(raw_json)

    hs_version = ""
    try:
        hs_version = f" <small>(v{haystack_version()})</small>"
    except Exception:
        pass

    # Search bar
    question = st.text_input("", value="", max_chars=100, on_change=reset_results)
    col1, col2 = st.columns(2)
    col1.markdown("<style>.stButton button {width:100%;}</style>", unsafe_allow_html=True)
    col2.markdown("<style>.stButton button {width:100%;}</style>", unsafe_allow_html=True)

    run_pressed = col2.button("Run")

    run_query = (
        run_pressed or question != st.session_state.question
    )

    with st.spinner("⌛️ &nbsp;&nbsp; Haystack is starting..."):
        if not haystack_is_ready():
            st.error("🚫 &nbsp;&nbsp; Connection Error. Is Haystack running?")
            run_query = False
            reset_results()

    # Get results for query
    if run_query and question:
        reset_results()
        st.session_state.question = question

        with st.spinner(
            "🧠 &nbsp;&nbsp; Performing neural search on documents... \n "
        ):
            try:
                st.session_state.results, st.session_state.raw_json = query(
                    question, top_k_reader=top_k_reader, top_k_retriever=top_k_retriever
                )
            except JSONDecodeError as je:
                st.error("👓 &nbsp;&nbsp; An error occurred reading the results. Is the document store working?")
                return
            except Exception as e:
                logging.exception(e)
                if "The server is busy processing requests" in str(e) or "503" in str(e):
                    st.error("🧑‍🌾 &nbsp;&nbsp; All our workers are busy! Try again later.")
                else:
                    st.error("🐞 &nbsp;&nbsp; An error occurred during the request.")
                    st.error(e)
                return

    if st.session_state.results:

        st.write("## Results:")

        for count, result in enumerate(st.session_state.results):
            if result["answer"]:
                answer = result["answer"] #, result["context"] , context
                # start_idx = context.find(answer)
                # end_idx = start_idx + len(answer)
                # Hack due to this bug: https://github.com/streamlit/streamlit/issues/3190
                st.write(
                    # markdown(context[:start_idx] + str(annotation(answer, "ANSWER", "#8ef")) + context[end_idx:]),
                    # unsafe_allow_html=True,
                    answer
                )
                # source = ""
                # url, title = get_backlink(result)
                # if url and title:
                #     source = f"[{result['document']['meta']['title']}]({result['document']['meta']['url']})"
                # else:
                #     source = f"{result['source']}"
                # st.markdown(f"**Relevance:** {result['relevance']} -  **Source:** {source}")

            else:
                st.info(
                    "🤔 &nbsp;&nbsp; Haystack is unsure whether any of the documents contain an answer to your question. Try to reformulate it!"
                )
                st.write("**Relevance:** ", result["relevance"])


main()