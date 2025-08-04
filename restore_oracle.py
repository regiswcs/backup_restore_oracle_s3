
import os
import subprocess
import datetime
import logging
import sys
from dotenv import load_dotenv

# --- 1. Carregar Variáveis de Ambiente ---
# Carrega as variáveis do arquivo .env para uso no script.
load_dotenv()

# --- 2. Configurações e Variáveis Globais ---
# Define os caminhos e nomes utilizados no processo de restauração.
LOG_DIR = os.path.normpath(os.getenv("LOG_DIR"))
RESTORE_SOURCE_DIR = os.path.normpath(os.getenv("RESTORE_SOURCE_DIR"))
ORACLE_SID = os.getenv("ORACLE_SID")
RMAN_TARGET_CONNECT_STRING = os.getenv("RMAN_TARGET_CONNECT_STRING")

# --- 3. Configurar Logging ---
# Configura um sistema de logs para registrar todas as operações,
# facilitando o rastreamento e a depuração.
os.makedirs(LOG_DIR, exist_ok=True)
log_file_name = datetime.datetime.now().strftime("restore_log_%Y%m%d_%H%M%S.log")
log_path = os.path.join(LOG_DIR, log_file_name)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.info("Iniciando script de restauração Oracle...")
logger.info(f"Log de execução salvo em: {log_path}")

def find_latest_backup_sets(backup_type):
    """
    Encontra os conjuntos de backups mais recentes (FULL ou INCREMENTAL)
    no diretório de backups temporários.
    """
    if not os.path.exists(RESTORE_SOURCE_DIR):
        logger.error(f"Diretório de backup temporário não encontrado: {RESTORE_SOURCE_DIR}")
        return None, None

    backup_runs = sorted([d for d in os.listdir(RESTORE_SOURCE_DIR) if os.path.isdir(os.path.join(RESTORE_SOURCE_DIR, d))], reverse=True)

    latest_full_run = None
    latest_incremental_run = None

    # Encontra o backup FULL mais recente
    for run in backup_runs:
        run_path = os.path.join(RESTORE_SOURCE_DIR, run)
        files = os.listdir(run_path)
        if any("DB_BACKUP_FULL" in f for f in files):
            latest_full_run = run_path
            break

    if not latest_full_run:
        logger.error("Nenhum backup FULL encontrado para a restauração.")
        return None, None

    if backup_type == 'INCREMENTAL':
        # Encontra o backup INCREMENTAL mais recente
        for run in backup_runs:
            run_path = os.path.join(RESTORE_SOURCE_DIR, run)
            files = os.listdir(run_path)
            if any("DB_BACKUP_INCREMENTAL" in f for f in files):
                latest_incremental_run = run_path
                break
        if not latest_incremental_run:
            logger.warning("Nenhum backup INCREMENTAL encontrado. A restauração será feita apenas com o FULL.")

    return latest_full_run, latest_incremental_run


def run_rman_restore(full_backup_path, incremental_backup_path=None):
    """
    Executa a restauração do banco de dados usando RMAN.
    """
    logger.info("Iniciando processo de restauração RMAN...")

    # Comandos RMAN para restauração
    rman_script_lines = [
        "RUN {",
        "SHUTDOWN IMMEDIATE;",
        "STARTUP MOUNT;",
        f"CATALOG START WITH '{full_backup_path}';",
    ]
    if incremental_backup_path:
        rman_script_lines.append(f"CATALOG START WITH '{incremental_backup_path}';")

    rman_script_lines.extend([
        "RESTORE DATABASE;",
        "RECOVER DATABASE;",
        "ALTER DATABASE OPEN;",
        "}"
    ])

    rman_script_content = "\n".join(rman_script_lines)
    logger.info("Script RMAN a ser executado:")
    logger.info(rman_script_content)

    rman_script_path = os.path.join(RESTORE_SOURCE_DIR, "rman_restore_script.rcv")
    with open(rman_script_path, 'w') as f:
        f.write(rman_script_content)

    command = [
        "rman",
        f"TARGET {RMAN_TARGET_CONNECT_STRING}",
        "NOCATALOG",
        f"CMDFILE={rman_script_path}"
    ]

    try:
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        logger.info("Restauração RMAN concluída com sucesso!")
        logger.debug(f"Saída RMAN STDOUT:\n{process.stdout}")
        if process.stderr:
            logger.warning(f"Saída RMAN STDERR:\n{process.stderr}")
        return True, "Restauração concluída com sucesso."
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro ao executar a restauração RMAN: {e}")
        logger.error(f"STDOUT RMAN:\n{e.stdout}")
        logger.error(f"STDERR RMAN:\n{e.stderr}")
        return False, f"Falha no RMAN: {e.stderr}"
    finally:
        if os.path.exists(rman_script_path):
            os.remove(rman_script_path)

def main():
    """
    Função principal para orquestrar a restauração.
    """
    if len(sys.argv) < 2 or sys.argv[1].upper() not in ['FULL', 'INCREMENTAL']:
        print("Uso: python restore_oracle.py [FULL|INCREMENTAL]")
        sys.exit(1)

    restore_type = sys.argv[1].upper()
    logger.info(f"Tipo de restauração solicitada: {restore_type}")

    full_backup_path, incremental_backup_path = find_latest_backup_sets(restore_type)

    if not full_backup_path:
        logger.error("Não foi possível encontrar um backup FULL para a restauração. Abortando.")
        sys.exit(1)

    if restore_type == 'INCREMENTAL' and not incremental_backup_path:
        logger.warning("Backup INCREMENTAL solicitado, mas não encontrado. Restaurando apenas o FULL.")
        restore_type = 'FULL' # Força a restauração FULL

    success, message = run_rman_restore(full_backup_path, incremental_backup_path if restore_type == 'INCREMENTAL' else None)

    if success:
        logger.info(message)
    else:
        logger.error(message)

if __name__ == "__main__":
    main()
