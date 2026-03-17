set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
COMPETITION_NAME="spaceship-titanic"

pxq add "pip install kaggle && mkdir -p ${COMPETITION_NAME} && kaggle competitions download -c ${COMPETITION_NAME} -p ${COMPETITION_NAME} && unzip ${COMPETITION_NAME}/*.zip -d /kaggle/input/${COMPETITION_NAME}" --config config/dataset-download.yaml
