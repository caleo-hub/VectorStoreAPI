import os
import json
import requests
from openai import AzureOpenAI


class ChatUtils:
    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2024-05-01-preview",
        )
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_ID")
        self.role_prompt = os.getenv("ROLE_PROMPT")
        self.teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
        self.initiate_assistant()

    def initiate_assistant(self):
        """
        Inicializa o cliente AzureOpenAI e o assistente.
        """
        self.assistant = self.client.beta.assistants.create(
            model=self.deployment,
            instructions=self.role_prompt,
            tools=self.get_chat_tools(),
            tool_resources={
                "file_search": {"vector_store_ids": [os.getenv(VECTOR_STORE_ID)]}
            },
            temperature=1,
            top_p=1,
        )

    def generate_summary(self, conversation_messages: list) -> str:
        """
        Gera um resumo do pedido do usuário com base nas mensagens anteriores.
        Apenas as mensagens com role 'user' são consideradas.
        """
        user_messages = []
        for msg in conversation_messages:
            if msg.role == "user":
                # Cada mensagem pode ter vários blocos; extrai o texto de cada bloco de tipo "text"
                for block in msg.content:
                    if block.type == "text" and hasattr(block, "text"):
                        user_messages.append(block.text.value)
        conversation_text = "\n".join(user_messages)
        summary_prompt = (
            "Resuma o pedido do usuário com base nas mensagens a seguir, "
            "destacando claramente o que ele deseja:\n\n"
            "Não fale que o usuário quer falar com agente via teams no resumo. "
            + conversation_text
            + "\n\nResumo:"
        )

        summary_response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": summary_prompt}],
            temperature=0.3,
            max_tokens=50,
        )
        raw_summary = json.loads(summary_response.model_dump_json())["choices"][0]
        summary_text = raw_summary.get("message", {}).get("content", "").strip()
        return summary_text

    def transfer_to_teams_agent(self, args, conversation_messages):
        """
        Esta função é chamada quando o usuário solicita falar com um agente via Teams.
        Ela gera um resumo do pedido do usuário (utilizando as mensagens anteriores)
        e dispara um trigger via webhook que posta uma mensagem em um canal do Teams via bot
        usando Adaptive Cards.
        """
        if not self.teams_webhook_url:
            print("Erro: TEAMS_WEBHOOK_URL não está configurada no .env")
            return

        summary_text = self.generate_summary(conversation_messages)
        card_text = f"O usuário gostaria de: {summary_text}\nVocê pode ajudar?"

        payload = {
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card_text,
                }
            ]
        }

        try:
            response = requests.post(self.teams_webhook_url, json=payload)
            response.raise_for_status()
            print("Mensagem enviada com sucesso para o Teams.")
        except requests.exceptions.RequestException as e:
            print(f"Erro ao enviar mensagem para o Teams: {e}")

    @staticmethod
    def get_chat_tools():
        """
        Retorna as ferramentas de chat disponíveis.
        """
        return [
            {
                "type": "file_search",
            },
            {
                "type": "function",
                "function": {
                    "name": "transfer_to_teams_agent",
                    "description": "Detecta quando o usuário deseja falar com um agente via Teams e realiza a transferência.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "A mensagem do usuário solicitando o contato com um agente via Teams",
                            }
                        },
                        "required": ["message"],
                    },
                },
            },
        ]
