import http.client, importlib.util, io, pathlib, socket, unittest, urllib.error
from unittest import mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('m8_runner',ROOT/'scripts/run_vlm_application_api_smoke.py')
RUNNER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(RUNNER)

class Response:
    def __init__(self,body=b'',status=200,reason='OK'):self.body=body;self.status=status;self.reason=reason;self.headers={}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return self.body

class RunnerEvidenceTest(unittest.TestCase):
    def test_success_and_empty_response(self):
        with mock.patch('urllib.request.urlopen',return_value=Response(b'')):
            text,evidence=RUNNER.perform_http_request('http://test',b'{}',1)
        self.assertEqual(text,'');self.assertEqual(evidence['http_status'],200);self.assertEqual(evidence['response_bytes'],0)
    def test_http_statuses_are_captured_and_classified(self):
        for status,classification in ((400,'request_rejected'),(404,'route_not_found'),(413,'payload_limit'),(500,'internal')):
            error=urllib.error.HTTPError('http://test',status,'reason',{},io.BytesIO(b'{"error":"safe"}'))
            with mock.patch('urllib.request.urlopen',side_effect=error):text,evidence=RUNNER.perform_http_request('http://test',b'{}',1)
            self.assertIsNone(text);self.assertEqual(evidence['http_status'],status);self.assertEqual(RUNNER.classify_failure(evidence),classification)
    def test_network_failures_are_distinct(self):
        cases=((urllib.error.URLError('refused'),'URLError'),(socket.timeout('late'),'TimeoutError'),(http.client.RemoteDisconnected('closed'),'RemoteDisconnected'))
        for error,name in cases:
            with mock.patch('urllib.request.urlopen',side_effect=error):_,evidence=RUNNER.perform_http_request('http://test',b'{}',1)
            self.assertEqual(evidence['exception_type'],name)
    def test_redacts_base64(self):
        redacted=RUNNER.redact_body(b'{"images":[{"data_base64":"SECRET"}]}')
        self.assertNotIn('SECRET',redacted)
    def test_malformed_sse_and_missing_events(self):
        with self.assertRaises(ValueError):RUNNER.parse_sse('event: token\n\n')
        self.assertEqual(RUNNER.parse_sse(''),[])
        metadata='event: metadata\ndata: {}\n\n';metadata_events=RUNNER.parse_sse(metadata);self.assertEqual([x['event'] for x in metadata_events],['metadata']);self.assertFalse(RUNNER.valid_sse_sequence(metadata_events))
        no_metadata=RUNNER.parse_sse('event: token\ndata: {}\n\nevent: done\ndata: {}\n\n');self.assertFalse(RUNNER.valid_sse_sequence(no_metadata))
        duplicate_terminal=RUNNER.parse_sse('event: metadata\ndata: {}\n\nevent: done\ndata: {}\n\nevent: done\ndata: {}\n\n');self.assertFalse(RUNNER.valid_sse_sequence(duplicate_terminal))
        valid=RUNNER.parse_sse('event: metadata\ndata: {}\n\nevent: token\ndata: {}\n\nevent: done\ndata: {}\n\n');self.assertTrue(RUNNER.valid_sse_sequence(valid))

if __name__=='__main__':unittest.main()
