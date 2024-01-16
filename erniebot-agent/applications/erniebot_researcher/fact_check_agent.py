import logging
import re
from typing import Any, Dict, List, Optional, Union

from tools.utils import JsonUtil, ReportCallbackHandler

from erniebot_agent.chat_models.erniebot import BaseERNIEBot
from erniebot_agent.memory import HumanMessage, Message, SystemMessage
from erniebot_agent.prompt import PromptTemplate

logger = logging.getLogger(__name__)
PLAN_VERIFICATIONS_PROMPT = """
为了验证给出内容中数字性表述是否正确，你需要生成一系列验证问题，以测试原始基线响应中的事实主张。
例如，如果长格式响应的一部分包含“墨西哥-美国战争
是 1846 年至 1848 年美国和墨西哥之间的武装冲突”，那么一种可能
检查这些日期的验证问题可以是 墨西哥-美国战争何时开始以及结束?
给出内容：{{base_context}}
你需要按照列表输出,并且需要输出段落中的事实和验证问题即可。
[{"fact":<段落中的事实>,"question":<验证问题，通过结合查询和事实生成>},{"fact":<段落中的事实>,"question":<验证问题，通过结合查询和事实生成>},...]
"""
ANWSER_PROMPT = """"你不具备任何知识，你只能根据外部知识回答问题。
如果给出的外部知识不能回答给出的问题，请你直接输出"无法回答"，不需要回答过的内容。
给出问题:\n{{question}}\n外部知识:{{content}}\n回答:"""
CHECK_CLAIM_PROMPT = """"请你根据给出的问题以及回答，你不需要作任何推理来，只需要判断给出的事实中数字描述是否正确。
如果你认为给出的事实中数字描述不正确，请根据给出的问题和回答，删除事实中数字描述对事实进行修正。
你的输出为json格式{"is_correct":<事实是否正确>,"modify":<对不正确的事实进行修正>}
给出问题:{{question}}\n回答:{{answer}}\n事实:{{claim}}"""
FINAL_RESPONSE_PROMPT = """你需要根据给出的背景知识要改写原始内容。必须保证改写内容中的数字来自于背景知识。
你必须要修正原始内容中的数字，并且保证改写后的内容中数字与背景知识中的数字一致。
原始内容：{{origin_content}}
背景知识：{{context}}
改进内容：
"""


class FactCheckerAgent(JsonUtil):
    DEFAULT_SYSTEM_MESSAGE = "你是一个事实检查助手，你的任务就是检查文本中的事实描述是否正确"

    def __init__(
        self,
        name: str,
        llm: BaseERNIEBot,
        retriever_db: Any,
        system_message: Optional[SystemMessage] = None,
        callbacks=None,
        config=None,
    ):
        self.name = name
        self.llm = llm
        self.retriever_db = retriever_db
        self.prompt_plan_verifications = PromptTemplate(
            PLAN_VERIFICATIONS_PROMPT, input_variables=["base_context"]
        )
        self.prompt_anwser = PromptTemplate(ANWSER_PROMPT, input_variables=["question", "content"])
        self.prompt_check_claim = PromptTemplate(
            CHECK_CLAIM_PROMPT, input_variables=["question", "answer", "claim"]
        )
        self.prompt_final_response = PromptTemplate(
            FINAL_RESPONSE_PROMPT, input_variables=["origin_content", "context"]
        )
        self.system_message = (
            system_message.content if system_message is not None else self.DEFAULT_SYSTEM_MESSAGE
        )
        if callbacks is None:
            self._callback_manager = ReportCallbackHandler()
        else:
            self._callback_manager = callbacks

    async def run(self, report: Union[str, dict]):
        await self._callback_manager.on_run_start(
            agent=self, agent_name=self.name, prompt=self.system_message
        )
        agent_resp = await self._run(report=report)
        await self._callback_manager.on_run_end(agent=self, response=agent_resp)
        return agent_resp

    async def generate_anwser(self, question: str, context: str):
        messages: List[Message] = [
            HumanMessage(content=self.prompt_anwser.format(question=question, content=context))
        ]
        responese = await self.llm.chat(messages)
        result = responese.content
        return result

    async def check_claim(self, question: str, answer: str, claim: str):
        messages: List[Message] = [
            HumanMessage(
                content=self.prompt_check_claim.format(question=question, answer=answer, claim=claim)
            )
        ]
        responese = await self.llm.chat(messages)
        result = responese.content
        result = self.parse_json(result)
        return result

    async def verifications(self, facts_problems: List[dict]):
        for item in facts_problems:
            question = item["question"]
            claim = item["fact"]
            context = self.retriever_db.search(question)
            context = [i["content"] for i in context]
            item["evidence"] = context
            anwser = await self.generate_anwser(question, context)
            item["anwser"] = anwser
            result = await self.check_claim(question, anwser, claim)
            item["is_correct"] = result["is_correct"]
            if result["is_correct"] is False:
                item["modify"] = result["modify"]
            else:
                item["modify"] = claim
        return facts_problems

    async def generate_final_response(self, content: str, verifications: List[dict]):
        if all([item["is_correct"] for item in verifications]):
            return content
        else:
            context = "".join([item["modify"] for item in verifications])
            messages: List[Message] = [
                HumanMessage(
                    content=self.prompt_final_response.format(origin_content=content, context=context)
                )
            ]
            resulte = await self.llm.chat(messages)
            result = resulte.content
            return result

    async def report_fact(self, report: str):
        report_list = report.split("\n\n")
        text = []
        for item in report_list:
            if item.strip()[0] == "#":
                text.append(item)
            else:
                contains_numbers = re.findall(r"\b\d+\b", item)
                if contains_numbers:
                    messages: List[Message] = [
                        HumanMessage(content=self.prompt_plan_verifications.format(base_context=item))
                    ]
                    responese = await self.llm.chat(messages)
                    result: List[dict] = self.parse_json(responese.content)
                    fact_check_result: List[dict] = await self.verifications(result)
                    new_item: str = await self.generate_final_response(item, fact_check_result)
                    text.append(new_item)
                else:
                    text.append(item)
        return "\n\n".join(text)

    async def _run(self, report: Union[str, Dict[str, str]]):
        if isinstance(report, dict):
            report = report["report"]
        report = await self.report_fact(report)
        return report
