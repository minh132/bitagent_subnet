# The MIT License (MIT)
# Copyright © 2023 RogueTensor

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import time
import random
from typing import List
from bitagent.protocol import QnATask
from bitagent.task_api.tasks import Task, TASK_WEIGHTS
from common.base.validator import BaseValidatorNeuron
from bitagent.task_api.criteria import default_criteria, gen_data_task_criteria

# QnA Task 
# these tasks look to test RAG implementations
# random selections of source data is selected from the task api dataset
# a question is generated for the random source data
# the question is checked for alignment with the text
# the question, along with source data, is then used to generate a QnA task
# generated task for n_texts of data looking for n_expected_citations of relevant citations (sources and contexts)
class GeneratedQnATask(Task):
    def __init__(self, validator: BaseValidatorNeuron, name: str, 
                 desc: str = "", n_texts:int = 3, n_expected_citations:int = 1, timeout:float = 10.0):
        super().__init__(name=name, desc=desc)
        self.name=self.name + f" for {n_texts} texts and {n_expected_citations} expected citations"
        self.validator=validator
        self.timeout=timeout
        self.weight = TASK_WEIGHTS['generated_qna']
        # countering the effect of setting seed for task orchestration from validators
        random.seed(None)

        datas = self.generate_random_texts(n_texts=n_texts)
        texts = [d['context'] for d in datas]
        sources = [d['source'] for d in datas]
        satisfied_with_question = False
        loop_count = 0
        while not satisfied_with_question:
            loop_count += 1
            selected_num=random.randrange(len(texts))
            selected_text = texts[selected_num]
            selected_source = sources[selected_num]
            question = self.get_question_for_text(text=selected_text)
            if loop_count > 10:
                satisfied_with_question = True # just gonna go with it :(
            else:
                satisfied_with_question = self.check_question_for_alignment_with_text(question, text=selected_text)
            if satisfied_with_question:
                pass #print('going with it')
            else:
                pass #print('nope')
    
        query_text = f"""Given the following CONTEXT:

            ```{selected_text}```
       
            Please provide the user with an answer to their question: {question}.
            Response: """
        response_gen = self.validator.validator_llm(query_text, temperature=0.8, max_new_tokens=2000)
        self.criteria=default_criteria+gen_data_task_criteria(selected_datas=[datas[selected_num]], n_expected_citations=n_expected_citations, response_gen=response_gen)
        notes = """The task is built from a prompt and a list of source context.
The task is to provide a reasonable response to the prompt and a list of citations that informed the response."""
        self.synapse=QnATask(prompt=question, urls=[], datas=datas, notes=notes)

    def generate_random_texts(self, n_texts: int = 3) -> [List[str], List[str]]:
        # get n random data
        # countering the effect of setting seed for task orchestration from validators
        random.seed(None)
        output = []
        for _ in range(n_texts):
            text = next(self.validator.qna_dataset)["text"]
            text = text[:1500]
            # arbitrary and random source ids
            h = random.getrandbits(128)
            source = f'{time.strftime("%Y%m%d")}.bitagent.source.{h}'
            output.append({'source':source,'context':text})
        return output

    def get_question_for_text(self, text: str) -> str:
        # for the simple model, use less text, truncate
        # current model (T5) takes 512 tokens, roughly 4 chars per token (per google PaLM 2), 1900 leaves us room for the rest of the prompt
        truc_text = text[:3300]
        input_text = f"""
            Ask a short 1-sentence question that is unique to this text, making sure to contain key phrases from the text such that the question can be answered by using this text and not other texts. Here is the text:
            ``` 
                {truc_text}
            ```
            Best Question:
        """
        question = self.validator.validator_llm(input_text, temperature=0.8)
        return question

    def check_question_for_alignment_with_text(self, question:str, text:str):
        score = self.validator.measure_relevance_of_texts(question, text)
        if score < 0.4:
            return False

        # bunch of common things we have seen that are too vague of questions
        if "What is the main " in question:
            return False

        if "What are the main " in question:
            return False

        if "author's" in question:
            return False

        if len(question) < 20:
            return False

        input_text = f"""
            Given this Question:
            ```
            {question}
            ```
            And this Context: 
            ```
            {text}
            ```
            Is the provided Question a strongly relevant question for the provided Context that is not a general question that can be ambiguous when selecting from a long list of text options.  In other words, are there enough details in the Question linked explicitly to the Context? Only respond with yes or no, no other words:
        """
        yes_or_no = self.validator.validator_llm(input_text)
        if yes_or_no.strip().lower() == "yes":
            return True
        return False 