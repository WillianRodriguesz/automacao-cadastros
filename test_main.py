"""Testes unitários das funções principais do main.py."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main

REGISTRO_OK = {"id": 1, "nome": "Maria Silva", "cpf": "12345678900", "status": "APROVADO"}


def registro(**alteracoes):
    """Devolve um registro aprovado e válido, com os campos alterados."""
    return {**REGISTRO_OK, **alteracoes}


class ComPastaTemporaria(unittest.TestCase):
    """Base: cada teste ganha uma pasta temporária, apagada no fim."""

    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)

    def escrever_json(self, conteudo):
        caminho = self.pasta / "solicitacoes.json"
        caminho.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
        return caminho


class TestCarregarSolicitacoes(ComPastaTemporaria):
    def test_le_a_lista_de_registros(self):
        entrada = self.escrever_json([registro(nome="José")])
        self.assertEqual(main.carregar_solicitacoes(entrada), [registro(nome="José")])

    def test_aceita_arquivo_com_bom(self):
        entrada = self.pasta / "com_bom.json"
        entrada.write_bytes(b"\xef\xbb\xbf" + json.dumps([REGISTRO_OK]).encode("utf-8"))
        self.assertEqual(main.carregar_solicitacoes(entrada), [REGISTRO_OK])

    def test_arquivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            main.carregar_solicitacoes(self.pasta / "nao_existe.json")

    def test_json_malformado(self):
        entrada = self.pasta / "malformado.json"
        entrada.write_text('[{"id": 1', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            main.carregar_solicitacoes(entrada)

    def test_raiz_que_nao_e_lista(self):
        entrada = self.escrever_json({"solicitacoes": []})
        with self.assertRaises(main.EstruturaInvalidaError):
            main.carregar_solicitacoes(entrada)


class TestAvaliarRegistro(unittest.TestCase):
    def test_aprovado_com_cpf_e_elegivel(self):
        self.assertIsNone(main.avaliar_registro(REGISTRO_OK, 1))

    def test_status_diferente_de_aprovado_e_regra_de_negocio(self):
        ignorado = main.avaliar_registro(registro(status="PENDENTE"), 1)
        self.assertFalse(ignorado.erro)
        self.assertIn("PENDENTE", ignorado.mensagem)
        self.assertEqual(ignorado.id, "id 1")

    def test_cpf_nulo_vazio_ou_so_espacos_e_erro(self):
        for cpf in (None, "", "   "):
            with self.subTest(cpf=cpf):
                ignorado = main.avaliar_registro(registro(cpf=cpf), 1)
                self.assertTrue(ignorado.erro)
                self.assertIn("cpf", ignorado.mensagem)

    def test_campo_obrigatorio_ausente(self):
        sem_cpf = {campo: valor for campo, valor in REGISTRO_OK.items() if campo != "cpf"}
        ignorado = main.avaliar_registro(sem_cpf, 1)
        self.assertTrue(ignorado.erro)
        self.assertIn("ausente", ignorado.mensagem)
        self.assertIn("cpf", ignorado.mensagem)

    def test_item_que_nao_e_objeto_e_identificado_pela_posicao(self):
        ignorado = main.avaliar_registro("texto solto", 3)
        self.assertTrue(ignorado.erro)
        self.assertEqual(ignorado.id, "posição 3")

    def test_nome_vazio_ou_id_invalido_e_erro(self):
        for alteracao in ({"nome": "  "}, {"id": None}, {"id": True}):
            with self.subTest(alteracao):
                self.assertTrue(main.avaliar_registro(registro(**alteracao), 1).erro)

    def test_status_vem_antes_do_cpf(self):
        # Um PENDENTE sem CPF é só "não aprovado": o CPF só importa para quem foi aprovado.
        ignorado = main.avaliar_registro(registro(status="PENDENTE", cpf=""), 1)
        self.assertFalse(ignorado.erro)

    def test_texto_que_nao_cabe_em_utf8_e_erro(self):
        ignorado = main.avaliar_registro(registro(nome="Emoji \ud83d cortado"), 1)
        self.assertTrue(ignorado.erro)
        self.assertIn("nome", ignorado.mensagem)

    def test_id_de_texto_nao_forja_linha_de_log(self):
        ignorado = main.avaliar_registro(registro(id="1\nlinha falsa", status="PENDENTE"), 1)
        self.assertNotIn("\n", ignorado.id)


class TestFiltrarAprovados(unittest.TestCase):
    def test_separa_aprovados_e_ignorados_mantendo_a_ordem(self):
        registros = [
            registro(id=1),
            registro(id=2, cpf=""),
            registro(id=3, status="PENDENTE"),
            "texto solto",
            registro(id=5, nome="  Ana  ", cpf=" 123 "),
        ]
        aprovados, ignorados = main.filtrar_aprovados(registros)

        self.assertEqual([item["id"] for item in aprovados], [1, 5])
        self.assertEqual(aprovados[1], {"id": 5, "nome": "Ana", "cpf": "123"})
        self.assertEqual([ignorado.id for ignorado in ignorados], ["id 2", "id 3", "posição 4"])
        self.assertEqual(len(aprovados) + len(ignorados), len(registros))


class TestGerarCsv(ComPastaTemporaria):
    def test_grava_cabecalho_virgula_e_acentos_em_utf8(self):
        saida = self.pasta / "aprovados.csv"
        main.gerar_csv([{"id": 1, "nome": "José D'Ávila", "cpf": "00123456789"}], saida)

        bruto = saida.read_bytes()
        self.assertEqual(bruto.decode("utf-8"), "id,nome,cpf\r\n1,José D'Ávila,00123456789\r\n")
        self.assertFalse(bruto.startswith(b"\xef\xbb\xbf"))  # sem BOM

    def test_lista_vazia_gera_so_o_cabecalho(self):
        saida = self.pasta / "aprovados.csv"
        main.gerar_csv([], saida)
        self.assertEqual(saida.read_bytes().decode("utf-8"), "id,nome,cpf\r\n")

    def test_pasta_inexistente_levanta_oserror(self):
        with self.assertRaises(OSError):
            main.gerar_csv([], self.pasta / "nao_existe" / "aprovados.csv")

    def test_falha_no_meio_preserva_o_csv_anterior(self):
        saida = self.pasta / "aprovados.csv"
        anterior = b"id,nome,cpf\r\n99,Anterior,111\r\n"
        saida.write_bytes(anterior)
        linhas = [{"id": 1, "nome": "Ok", "cpf": "1"}, {"id": 2, "nome": "x\ud800y", "cpf": "2"}]

        with self.assertRaises(UnicodeEncodeError):
            main.gerar_csv(linhas, saida)

        self.assertEqual(saida.read_bytes(), anterior)
        self.assertEqual([arquivo.name for arquivo in self.pasta.iterdir()], ["aprovados.csv"])


class TestExecutar(ComPastaTemporaria):
    def rodar(self, entrada=None, saida=None, arquivo_log=None):
        """Roda executar sem poluir o console e devolve (código de saída, texto do log)."""
        entrada = entrada or self.pasta / "solicitacoes.json"
        saida = saida or self.pasta / "aprovados.csv"
        arquivo_log = arquivo_log or self.pasta / "processamento.log"
        with contextlib.redirect_stdout(io.StringIO()):
            codigo = main.executar(entrada, saida, arquivo_log)
        texto = arquivo_log.read_text(encoding="utf-8") if arquivo_log.exists() else ""
        return codigo, texto

    def test_sucesso_com_o_arquivo_de_exemplo(self):
        codigo, log = self.rodar(entrada=main.ARQUIVO_ENTRADA)

        linhas = (self.pasta / "aprovados.csv").read_bytes().decode("utf-8").splitlines()
        self.assertEqual(codigo, 0)
        self.assertEqual([linha.split(",")[0] for linha in linhas[1:]], ["1", "4", "6", "9", "12", "13", "15"])
        self.assertIn("Total de registros lidos: 15", log)
        self.assertIn("Registros exportados: 7", log)
        self.assertIn("Registros ignorados: 8", log)
        self.assertTrue(log.rstrip().endswith("Resultado final: SUCESSO"))

    def test_registro_com_erro_nao_interrompe_o_processamento(self):
        self.escrever_json([registro(id=1), registro(id=2, cpf=None), registro(id=3)])
        codigo, log = self.rodar()

        self.assertEqual(codigo, 0)
        self.assertIn("WARNING  | Registro ignorado (id 2): cpf nulo", log)
        self.assertIn("Registros exportados: 2", log)

    def test_arquivo_de_entrada_inexistente(self):
        codigo, log = self.rodar()

        self.assertEqual(codigo, 1)
        self.assertIn("Arquivo de entrada não encontrado", log)
        self.assertTrue(log.rstrip().endswith("Resultado final: FALHA"))
        self.assertFalse((self.pasta / "aprovados.csv").exists())

    def test_json_invalido(self):
        (self.pasta / "solicitacoes.json").write_text("[{", encoding="utf-8")
        codigo, log = self.rodar()

        self.assertEqual(codigo, 1)
        self.assertIn("JSON inválido", log)

    def test_falha_ao_gravar_o_csv(self):
        self.escrever_json([registro()])
        codigo, log = self.rodar(saida=self.pasta / "nao_existe" / "aprovados.csv")

        self.assertEqual(codigo, 1)
        self.assertIn("Falha ao gravar o CSV", log)

    def test_log_que_nao_pode_ser_criado(self):
        self.escrever_json([registro()])
        with contextlib.redirect_stderr(io.StringIO()) as erro:
            codigo, _ = self.rodar(arquivo_log=self.pasta / "nao_existe" / "processamento.log")

        self.assertEqual(codigo, 1)
        self.assertIn("Não foi possível criar o arquivo de log", erro.getvalue())
        self.assertFalse((self.pasta / "aprovados.csv").exists())

    def test_falha_inesperada_devolve_codigo_2(self):
        self.escrever_json([registro()])
        with mock.patch.object(main, "filtrar_aprovados", side_effect=RuntimeError("boom")):
            codigo, log = self.rodar()

        self.assertEqual(codigo, 2)
        self.assertIn("Falha inesperada durante o processamento", log)

    def test_execucoes_repetidas_acrescentam_ao_log(self):
        self.escrever_json([registro()])
        self.rodar()
        _, log = self.rodar()

        self.assertEqual(log.count("Processamento iniciado"), 2)


if __name__ == "__main__":
    unittest.main()
