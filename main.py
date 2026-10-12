"""Automação de solicitações cadastrais: seleciona as aprovadas e gera o CSV."""

import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import NamedTuple

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_ENTRADA = BASE_DIR / "solicitacoes.json"
ARQUIVO_SAIDA = BASE_DIR / "aprovados.csv"
ARQUIVO_LOG = BASE_DIR / "processamento.log"
NOME_LOGGER = "automacao_cadastros"
STATUS_APROVADO = "APROVADO"
CAMPOS_OBRIGATORIOS = ("id", "nome", "cpf", "status")
COLUNAS_CSV = ("id", "nome", "cpf")
# Códigos de saída
CODIGO_SUCESSO = 0
CODIGO_FALHA_TRATADA = 1
CODIGO_FALHA_INESPERADA = 2
# Nome dado aos handlers criados por configurar_log
MARCA_HANDLER = f"{NOME_LOGGER}.handler"


class EstruturaInvalidaError(Exception):
    """JSON válido, mas a raiz não é uma lista."""


class RegistroIgnorado(NamedTuple):
    """Registro que não foi exportado: erro=True é dado inválido, erro=False é regra de negócio"""
    id: str
    mensagem: str
    erro: bool = True


def configurar_log(caminho: Path) -> logging.Logger:
    """Configura o logger da aplicação, com saída em arquivo (append) e no console."""
    logger = logging.getLogger(NOME_LOGGER)
    encerrar_log(logger)

    # O arquivo é aberto antes de instalar qualquer handler: se falhar, nada fica instalado.
    arquivo = logging.FileHandler(caminho, mode="a", encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    formato = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    for handler in (arquivo, console):
        handler.set_name(MARCA_HANDLER)
        handler.setFormatter(formato)
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def encerrar_log(logger: logging.Logger) -> None:
    """Remove e fecha os handlers instalados por configurar_log."""
    for handler in list(logger.handlers):
        if handler.get_name() == MARCA_HANDLER:
            logger.removeHandler(handler)
            handler.close()


def carregar_solicitacoes(caminho: Path) -> list:
    """Lê o JSON de solicitações"""
    
    dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    if not isinstance(dados, list):
        raise EstruturaInvalidaError(
            f"a raiz do JSON deve ser uma lista, mas foi encontrado {type(dados).__name__}"
        )
    return dados


def avaliar_registro(registro: object, posicao: int) -> RegistroIgnorado | None:
    """Devolve None se o registro for elegível ou o RegistroIgnorado da primeira regra violada"""
    id_log = f"posição {posicao}"

    # Regra 1: o item precisa ser um objeto JSON.
    if not isinstance(registro, dict):
        mensagem = f"registro não é um objeto (tipo: {type(registro).__name__})"
        return RegistroIgnorado(id_log, mensagem)

    valor_id = registro.get("id")
    id_inteiro = isinstance(valor_id, int) and not isinstance(valor_id, bool)
    id_texto_preenchido = isinstance(valor_id, str) and bool(valor_id.strip())
    id_valido = id_inteiro or id_texto_preenchido
    if id_valido:
        id_log = f"id {repr(str(valor_id))[1:-1]}"

    # Regra 2: as quatro chaves precisam existir.
    ausentes = [campo for campo in CAMPOS_OBRIGATORIOS if campo not in registro]
    if ausentes:
        mensagem = f"campo(s) obrigatório(s) ausente(s): {', '.join(ausentes)}"
        return RegistroIgnorado(id_log, mensagem)

    # Regra 3: só segue quem está APROVADO. É regra de negócio, não erro de dado.
    status = registro["status"]
    if status != STATUS_APROVADO:
        mensagem = f"status {status!r} diferente de {STATUS_APROVADO}"
        return RegistroIgnorado(id_log, mensagem, erro=False)

    # Regra 4: o cpf precisa estar preenchido (os dígitos não são validados).
    cpf = registro["cpf"]
    if cpf is None:
        return RegistroIgnorado(id_log, "cpf nulo")
    if not isinstance(cpf, str):
        return RegistroIgnorado(id_log, f"cpf com tipo inválido ({type(cpf).__name__})")
    if not cpf.strip():
        return RegistroIgnorado(id_log, "cpf vazio ou só espaços")

    # Regra 5: o nome precisa estar preenchido.
    nome = registro["nome"]
    if not isinstance(nome, str) or not nome.strip():
        return RegistroIgnorado(id_log, "nome vazio ou inválido")

    # Regra 6: o id precisa ser um inteiro ou um texto preenchido (avaliado no início).
    if not id_valido:
        return RegistroIgnorado(id_log, f"id inválido ({valor_id!r})")

    # Regra 7: os textos precisam caber em UTF-8.
    invalidos = []
    for campo, valor in (("id", valor_id), ("nome", nome), ("cpf", cpf)):
        try:
            str(valor).encode("utf-8") 
        except UnicodeEncodeError:
            invalidos.append(campo)
    if invalidos:
        mensagem = f"caracteres inválidos para UTF-8 em: {', '.join(invalidos)}"
        return RegistroIgnorado(id_log, mensagem)
    return None


def filtrar_aprovados(registros: list) -> tuple[list[dict], list[RegistroIgnorado]]:
    """Separa os registros elegíveis mantendo a ordem da entrada"""
    aprovados: list[dict] = []
    ignorados: list[RegistroIgnorado] = []
    for posicao, registro in enumerate(registros, start=1):
        ignorado = avaliar_registro(registro, posicao)
        if ignorado is None:
            aprovados.append(
                {
                    "id": registro["id"],
                    "nome": registro["nome"].strip(),
                    "cpf": registro["cpf"].strip(),
                }
            )
        else:
            ignorados.append(ignorado)
    return aprovados, ignorados


def gerar_csv(aprovados: list[dict], caminho: Path) -> None:
    """Grava os aprovados em CSV UTF-8"""
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        with temporario.open("w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS_CSV)
            escritor.writeheader()
            escritor.writerows(aprovados)
        temporario.replace(caminho)
    finally:
        temporario.unlink(missing_ok=True)


def _processar(logger: logging.Logger, entrada: Path, saida: Path) -> bool:
    """Lê, filtra e grava o CSV; devolve False quando uma falha tratada interrompe o fluxo"""
    logger.info(f"Lendo solicitações de {entrada}")
    try:
        registros = carregar_solicitacoes(entrada)
    except FileNotFoundError:
        logger.error(f"Arquivo de entrada não encontrado: {entrada}")
        return False
    except json.JSONDecodeError as erro:
        logger.error(f"JSON inválido em {entrada}: {erro}")
        return False
    except UnicodeDecodeError:
        logger.error(f"Arquivo de entrada não está em UTF-8: {entrada}")
        return False
    except EstruturaInvalidaError as erro:
        logger.error(f"Estrutura inesperada em {entrada}: {erro}")
        return False
    except OSError as erro:
        logger.error(f"Não foi possível ler {entrada}: {erro}")
        return False

    logger.info(f"Total de registros lidos: {len(registros)}")
    aprovados, ignorados = filtrar_aprovados(registros)
    for ignorado in ignorados:
        registrar = logger.warning if ignorado.erro else logger.info
        registrar(f"Registro ignorado ({ignorado.id}): {ignorado.mensagem}")

    try:
        gerar_csv(aprovados, saida)
    except OSError as erro:
        logger.error(f"Falha ao gravar o CSV {saida}: {erro}")
        return False

    logger.info(f"CSV gerado: {saida}")
    if not aprovados:
        logger.warning("Nenhum registro elegível")
    logger.info(f"Registros exportados: {len(aprovados)}")
    logger.info(f"Registros ignorados: {len(ignorados)}")
    return True


def executar(entrada: Path, saida: Path, arquivo_log: Path) -> int:
    """Executa o fluxo completo e devolve o código de saída"""
    try:
        logger = configurar_log(arquivo_log)
    except OSError as erro:
        print(f"Não foi possível criar o arquivo de log {arquivo_log}: {erro}", file=sys.stderr)
        return CODIGO_FALHA_TRATADA

    inicio_execucao = time.perf_counter()
    codigo = CODIGO_FALHA_INESPERADA
    try:
        logger.info("Processamento iniciado")
        concluiu = _processar(logger, entrada, saida)
        codigo = CODIGO_SUCESSO if concluiu else CODIGO_FALHA_TRATADA
    except Exception:
        logger.exception("Falha inesperada durante o processamento")
    finally:
        duracao = time.perf_counter() - inicio_execucao
        if codigo == CODIGO_SUCESSO:
            logger.info(f"Processamento concluído em {duracao:.2f}s")
            logger.info("Resultado final: SUCESSO")
        else:
            logger.error(f"Processamento interrompido após {duracao:.2f}s")
            logger.error("Resultado final: FALHA")
        encerrar_log(logger)
    return codigo


def main() -> int:
    return executar(ARQUIVO_ENTRADA, ARQUIVO_SAIDA, ARQUIVO_LOG)


if __name__ == "__main__":
    sys.exit(main())
