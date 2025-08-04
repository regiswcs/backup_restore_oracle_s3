
import os
import subprocess
import datetime
import shutil
from dotenv import load_dotenv
import boto3
import logging
import sys

# --- 1. Carregar Variáveis de Ambiente ---
load_dotenv()

# --- 2. Configurações e Variáveis Globais ---
LOG_DIR = os.path.normpath(os.getenv("LOG_DIR"))
TEMP_BACKUP_DIR = os.path.normpath(os.getenv("TEMP_BACKUP_DIR"))
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_BACKUP_PREFIX = os.getenv("S3_BACKUP_PREFIX", "oracle_backup/")
S3_LOG_PREFIX = os.getenv("S3_LOG_PREFIX", "oracle_logs/")
ORACLE_SID = os.getenv("ORACLE_SID")
RMAN_TARGET_CONNECT_STRING = os.getenv("RMAN_TARGET_CONNECT_STRING")
AWS_REGION = os.getenv("AWS_REGION")

# --- 3. Configurar Logging ---
os.makedirs(LOG_DIR, exist_ok=True)

backup_type_for_log = "UNKNOWN"
if len(sys.argv) > 1 and sys.argv[1].upper() in ["FULL", "INCREMENTAL"]:
    backup_type_for_log = sys.argv[1].upper()

log_file_name = datetime.datetime.now().strftime(f"backup_log_{backup_type_for_log}_%Y%m%d_%H%M%S.log")
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

logger.info("Iniciando script de backup Oracle para S3...")
logger.info(f"Log de execução salvo em: {log_path}")
logger.info(f"Diretório de backups temporários: {TEMP_BACKUP_DIR}")
logger.info(f"Bucket S3 de destino: {S3_BUCKET_NAME}")
logger.info(f"Prefixo S3 para Backups: {S3_BACKUP_PREFIX}")
logger.info(f"Prefixo S3 para Logs: {S3_LOG_PREFIX}")
logger.info(f"Oracle SID: {ORACLE_SID}")

# --- 4. Funções de Backup e Upload ---
def run_rman_backup(backup_type, output_dir):
    logger.info(f"Iniciando backup RMAN: {backup_type}...")
    timestamp = datetime.datetime.now().strftime('%m%d%H%M%S')
    backup_tag = f"BK_{backup_type}_{timestamp}"
    
    if backup_type == 'INCREMENTAL':
        db_backup_command = f"BACKUP INCREMENTAL LEVEL 1 DATABASE FORMAT '{output_dir}{os.sep}db_backup_{backup_type}_%U' TAG '{backup_tag}';"
    else:
        db_backup_command = f"BACKUP DATABASE FORMAT '{output_dir}{os.sep}db_backup_{backup_type}_%U' TAG '{backup_tag}';"
        
    archivelog_backup_command = f"BACKUP ARCHIVELOG ALL FORMAT '{output_dir}{os.sep}archivelog_%U';"
    delete_archivelog_command = "DELETE NOPROMPT ARCHIVELOG ALL COMPLETED BEFORE 'SYSDATE-1';"

    rman_script_lines = [
        "RUN {",
        "ALLOCATE CHANNEL d1 TYPE DISK;",
        db_backup_command,
        archivelog_backup_command,
        delete_archivelog_command,
        "RELEASE CHANNEL d1;",
        "}",
        "exit;"
    ]
    
    rman_script_content = "\n".join(rman_script_lines)
    logger.info("Conteúdo do script RMAN a ser gerado:")
    logger.info(f"\n{rman_script_content}")

    rman_script_path = os.path.join(TEMP_BACKUP_DIR, f"rman_script_{backup_type}.rcv")
    try:
        with open(rman_script_path, 'w') as f:
            f.write(rman_script_content)
        logger.info(f"Script RMAN gerado em: {rman_script_path}")
    except IOError as e:
        logger.error(f"Erro ao criar script RMAN: {e}")
        return False, f"Erro ao criar script RMAN: {e}"

    command = [
        "rman",
        f"TARGET {RMAN_TARGET_CONNECT_STRING}",
        f"NOCATALOG",
        f"CMDFILE={rman_script_path}"
    ]

    try:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Diretório de saída RMAN garantido: {output_dir}")

        process = subprocess.run(command, capture_output=True, text=True, check=True)
        logger.info(f"Comando RMAN executado com sucesso para {backup_type} e logs!")
        logger.debug(f"Saída RMAN STDOUT:\n{process.stdout}")
        if process.stderr:
            logger.warning(f"Saída RMAN STDERR (warnings/info):\n{process.stderr}")

        return True, "Backup RMAN concluído com sucesso."

    except subprocess.CalledProcessError as e:
        logger.error(f"Erro ao executar comando RMAN para {backup_type}: {e}")
        logger.error(f"STDOUT RMAN:\n{e.stdout}")
        logger.error(f"STDERR RMAN:\n{e.stderr}")
        return False, f"Falha no RMAN: {e.stderr}"
    except FileNotFoundError:
        logger.error("Comando 'rman' não encontrado. Verifique se o RMAN está no PATH.")
        return False, "Comando 'rman' não encontrado. Verifique se o RMAN está no PATH."
    except Exception as e:
        logger.error(f"Erro inesperado durante a execução do RMAN: {e}")
        return False, f"Erro inesperado durante o backup RMAN: {e}"
    finally:
        if os.path.exists(rman_script_path):
            try:
                os.remove(rman_script_path)
                logger.info(f"Script RMAN temporário removido: {rman_script_path}")
            except Exception as e:
                logger.warning(f"Falha ao remover script RMAN temporário: {e}")

def upload_to_s3(local_file_path, s3_key):
    logger.info(f"Iniciando upload para S3: {local_file_path} -> s3://{S3_BUCKET_NAME}/{s3_key}")
    s3_client = boto3.client('s3', region_name=AWS_REGION)
    try:
        s3_client.upload_file(local_file_path, S3_BUCKET_NAME, s3_key)
        logger.info(f"Upload para S3 concluído com sucesso: {s3_key}")
        return True
    except Exception as e:
        logger.error(f"Erro ao fazer upload para S3: {e}")
        return False

def upload_and_clean_logs(current_log_path, backup_type):
    log_filename = os.path.basename(current_log_path)
    s3_log_key = f"{S3_LOG_PREFIX}{log_filename}"
    logger.info(f"Iniciando upload do arquivo de log: {log_filename}")
    if upload_to_s3(current_log_path, s3_log_key):
        logger.info("Upload do arquivo de log para S3 concluído com sucesso.")
    else:
        logger.error("Falha no upload do arquivo de log para S3. A limpeza de logs locais continuará.")

    logger.info("Iniciando limpeza de logs locais...")
    try:
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        all_local_logs = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith('backup_log_') and f.endswith('.log')]

        full_logs = [f for f in all_local_logs if "_FULL_" in os.path.basename(f)]
        latest_full_log = max(full_logs, key=os.path.getctime) if full_logs else None

        logs_to_keep = set()
        if latest_full_log:
            logs_to_keep.add(latest_full_log)
            logger.info(f"Log de backup FULL mais recente a ser mantido: {os.path.basename(latest_full_log)}")

        incremental_logs_today = [f for f in all_local_logs if f"_INCREMENTAL_{today_str}" in os.path.basename(f)]
        for log in incremental_logs_today:
            logs_to_keep.add(log)
            logger.info(f"Log de backup INCREMENTAL de hoje a ser mantido: {os.path.basename(log)}")
        
        logs_to_keep.add(current_log_path)

        for log_file in all_local_logs:
            if log_file not in logs_to_keep:
                try:
                    os.remove(log_file)
                    logger.info(f"Log local obsoleto removido: {os.path.basename(log_file)}")
                except OSError as e:
                    logger.warning(f"Falha ao remover o arquivo de log local '{os.path.basename(log_file)}': {e}")

    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado durante a limpeza de logs locais: {e}")


def main():
    backup_type = backup_type_for_log
    if backup_type == "UNKNOWN":
        logger.error("ERRO: Tipo de backup (FULL ou INCREMENTAL) não especificado ou inválido.")
        logger.info("Uso: python backup_oracle_s3.py [FULL|INCREMENTAL]")
        sys.exit(1)

    logger.info(f"Tipo de backup a ser executado: {backup_type}")

    run_temp_dir = os.path.join(TEMP_BACKUP_DIR, datetime.datetime.now().strftime("%Y%m%d_%H%M%S_run"))
    os.makedirs(run_temp_dir, exist_ok=True)
    logger.info(f"Diretório temporário para esta execução: {run_temp_dir}")

    success_rman, message_rman = run_rman_backup(backup_type, run_temp_dir)

    if success_rman:
        generated_files = [f for f in os.listdir(run_temp_dir) if os.path.isfile(os.path.join(run_temp_dir, f))]
        
        if not generated_files:
            logger.error(f"Nenhum arquivo de backup encontrado no diretório de execução temporário '{run_temp_dir}' após o RMAN.")
            return

        logger.info(f"Total de {len(generated_files)} arquivo(s) de backup RMAN gerado(s) localmente.")

        all_uploads_successful = True
        for single_backup_file in generated_files:
            local_backup_full_path = os.path.join(run_temp_dir, single_backup_file)
            
            s3_key = f"{S3_BACKUP_PREFIX}{backup_type.lower()}/{single_backup_file}"

            logger.info(f"Tentando upload do arquivo: {single_backup_file} para s3://{S3_BUCKET_NAME}/{s3_key}")
            success_s3_single_file = upload_to_s3(local_backup_full_path, s3_key)
            
            if not success_s3_single_file:
                all_uploads_successful = False
                logger.error(f"Falha no upload do arquivo '{single_backup_file}'.")
            else:
                logger.info(f"Upload de '{single_backup_file}' para S3 concluído.")
        
        if all_uploads_successful:
            logger.info("Todos os arquivos de backup foram enviados para o S3 com sucesso!")
            try:
                shutil.rmtree(run_temp_dir)
                logger.info(f"Diretório de execução temporário removido: {run_temp_dir}")
            except Exception as e:
                logger.error(f"Falha na limpeza do diretório temporário '{run_temp_dir}': {e}")
        else:
            logger.error("Alguns uploads para S3 falharam. O diretório de backup local NÃO será excluído.")
            
    else:
        logger.error(f"Falha na geração do backup RMAN: {message_rman}.")

    upload_and_clean_logs(log_path, backup_type)

    logger.info("Script de backup finalizado.")

if __name__ == "__main__":
    main()
