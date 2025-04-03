import azure.functions as func
import logging
import json
import time
import dotenv
from utils.chat_utils import ChatUtils

dotenv.load_dotenv()

# Inicializa o cliente AzureOpenAI e o assistente
chat_utils = ChatUtils()
client = chat_utils.client
assistant = chat_utils.assistant

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="chatbotapi")
def chatbotapi(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse("JSON inválido", status_code=400)

    # Extrai os campos do body: role, content e, opcionalmente, threadId
    role = req_body.get("role")
    content = req_body.get("content")
    thread_id = req_body.get("threadId")

    if not role or not content:
        return func.HttpResponse(
            "Campos 'role' e 'content' são obrigatórios.", status_code=400
        )

    # Se threadId não for enviado, cria um novo thread; caso contrário, recupera o thread existente
    if not thread_id:
        thread = client.beta.threads.create()
        thread_id = thread.id
    else:
        thread = client.beta.threads.retrieve(thread_id=thread_id)

    # Adiciona a nova mensagem ao thread (o histórico já é mantido internamente)
    client.beta.threads.messages.create(thread_id=thread_id, role=role, content=content)

    # Inicia a execução do thread pelo assistente
    run = client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=assistant.id
    )

    # Aguarda até que a execução seja finalizada
    while run.status in ["queued", "in_progress", "cancelling"]:
        time.sleep(1)
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

    # Processa a resposta do assistente
    citations = []
    answer = ""
    if run.status == "completed":
        # Filtra somente as mensagens geradas no run atual
        messages = list(
            client.beta.threads.messages.list(thread_id=thread_id, run_id=run.id)
        )
        assistant_message = next(
            (msg for msg in reversed(messages) if msg.role == "assistant"), None
        )
        if assistant_message:
            answer_parts = []
            # Concatena os blocos de texto da resposta, tratando as citações
            for block in assistant_message.content:
                if block.type == "text" and hasattr(block, "text"):
                    text_value = block.text.value
                    for index, annotation in enumerate(block.text.annotations or []):
                        text_value = text_value.replace(annotation.text, f"[{index}]")
                        if file_citation := getattr(annotation, "file_citation", None):
                            cited_file = client.files.retrieve(file_citation.file_id)
                            citations.append(f"{cited_file.filename}")
                    answer_parts.append(text_value)
            answer = "".join(answer_parts)
        else:
            answer = "Nenhuma resposta encontrada."
    elif run.status == "requires_action":
        for tool in run.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name == "transfer_to_teams_agent":
                # Executa a função de transferência para o agente via Teams
                conversation_history = list(
                    client.beta.threads.messages.list(thread_id=thread_id)
                )
                chat_utils.transfer_to_teams_agent(
                    tool.function.arguments, conversation_history
                )
                answer = "Transferência para agente via Teams iniciada."
            else:
                answer = "Função não reconhecida."
    else:
        answer = f"Falha na execução do thread: {run.status}"

    response_body = {"threadId": thread_id, "answer": answer, "citations": citations}

    return func.HttpResponse(
        json.dumps(response_body), status_code=200, mimetype="application/json"
    )
