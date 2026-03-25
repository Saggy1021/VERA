"""
VERA — Consent Manager (GDPR Article 7 + Article 9)
Biometric data (face embeddings, voice prints) is "special category"
data under GDPR. Explicit informed consent must be obtained before
any biometric processing begins.
"""
import time
import logging
import os

logger = logging.getLogger(__name__)

BIOMETRIC_DATA_PURPOSES = [
    "Identity verification: confirming you are the enrolled exam candidate",
    "Behavioral analysis: detecting exam policy violations in real time",
    "Voice verification: detecting presence of unauthorized assistance",
    "Evidence recording: preserving video clips for proctor review",
]

DATA_RETENTION_DAYS = 90
DATA_CONTROLLER = os.getenv('VERA_DATA_CONTROLLER', 'Your Organization Name')
DPO_EMAIL = os.getenv('VERA_DPO_EMAIL', 'privacy@yourorganization.com')


class ConsentRecord:
    def __init__(self, session_id: str, candidate_id: str):
        self.session_id = session_id
        self.candidate_id = candidate_id
        self.given = False
        self.timestamp = None
        self.ip_address = None
        self.purposes_accepted = []

    def to_dict(self) -> dict:
        return {
            'session_id': self.session_id,
            'candidate_id': self.candidate_id,
            'consent_given': self.given,
            'timestamp': self.timestamp,
            'ip_address': self.ip_address,
            'purposes': self.purposes_accepted,
            'data_controller': DATA_CONTROLLER,
            'dpo_email': DPO_EMAIL,
            'retention_days': DATA_RETENTION_DAYS
        }


class ConsentManager:
    """
    GDPR consent gate for biometric processing.
    Call require_consent() before any biometric data is processed.
    Processing MUST NOT begin if consent is not given.
    Consent record is stored in the audit log.
    """

    def __init__(self):
        self._records = {}

    def create_consent_request(self, session_id: str, candidate_id: str) -> dict:
        """
        Returns the consent request payload to send to the frontend.
        The frontend must display this and collect explicit confirmation.
        """
        record = ConsentRecord(session_id, candidate_id)
        self._records[session_id] = record

        return {
            'session_id': session_id,
            'requires_consent': True,
            'data_controller': DATA_CONTROLLER,
            'dpo_email': DPO_EMAIL,
            'retention_days': DATA_RETENTION_DAYS,
            'purposes': BIOMETRIC_DATA_PURPOSES,
            'withdrawal_notice': (
                'You may withdraw consent at any time. Withdrawal will end '
                'the exam session and no further biometric data will be processed.'
            )
        }

    def record_consent(self, session_id: str, given: bool,
                       ip_address: str = None) -> dict:
        """
        Record the candidate's consent decision.
        Returns the consent record for storage in the audit log.
        """
        if session_id not in self._records:
            logger.warning(f"ConsentManager: No pending request for {session_id}")
            return {'success': False, 'error': 'No pending consent request.'}

        record = self._records[session_id]
        record.given = given
        record.timestamp = time.time()
        record.ip_address = ip_address
        record.purposes_accepted = BIOMETRIC_DATA_PURPOSES if given else []

        action = 'GIVEN' if given else 'DECLINED'
        logger.info(f"ConsentManager: Consent {action} for session {session_id}")
        return {'success': True, 'consent_given': given, 'record': record.to_dict()}

    def is_consent_given(self, session_id: str) -> bool:
        """
        Check if consent has been given for this session.
        Returns False if no record exists or if consent was declined.
        The pipeline MUST check this before processing biometric data.
        """
        record = self._records.get(session_id)
        return record is not None and record.given

    def get_record(self, session_id: str):
        return self._records.get(session_id)

    def cleanup(self, session_id: str):
        self._records.pop(session_id, None)
