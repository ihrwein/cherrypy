from cherrypy.test import test
test.prefer_parent_path()

import sys
import gzip, StringIO
from httplib import IncompleteRead
import cherrypy
europoundUnicode = u'\x80\xa3'
sing = u"\u6bdb\u6cfd\u4e1c: Sing, Little Birdie?"
sing8 = sing.encode('utf-8')
sing16 = sing.encode('utf-16')


def setup_server():
    class Root:
        def index(self, param):
            assert param == europoundUnicode, "%r != %r" % (param, europoundUnicode)
            yield europoundUnicode
        index.exposed = True
        
        def mao_zedong(self):
            return sing
        mao_zedong.exposed = True
        
        def utf8(self):
            return sing8
        utf8.exposed = True
        utf8._cp_config = {'tools.encode.encoding': 'utf-8'}
        
        def reqparams(self, *args, **kwargs):
            return repr(cherrypy.request.params)
        reqparams.exposed = True
    
    class GZIP:
        def index(self):
            yield "Hello, world"
        index.exposed = True
        
        def noshow(self):
            # Test for ticket #147, where yield showed no exceptions (content-
            # encoding was still gzip even though traceback wasn't zipped).
            raise IndexError()
            yield "Here be dragons"
        noshow.exposed = True
        # Turn encoding off so the gzip tool is the one doing the collapse.
        noshow._cp_config = {'tools.encode.on': False}
        
        def noshow_stream(self):
            # Test for ticket #147, where yield showed no exceptions (content-
            # encoding was still gzip even though traceback wasn't zipped).
            raise IndexError()
            yield "Here be dragons"
        noshow_stream.exposed = True
        noshow_stream._cp_config = {'response.stream': True}
    
    root = Root()
    root.gzip = GZIP()
    cherrypy.tree.mount(root, config={'/gzip': {'tools.gzip.on': True}})



from cherrypy.test import helper


class EncodingTests(helper.CPWebCase):
    
    def testDecoding(self):
        europoundUtf8 = europoundUnicode.encode('utf-8')
        self.getPage('/?param=' + europoundUtf8)
        self.assertBody(europoundUtf8)
        
        # Encoded utf8 query strings MUST be parsed correctly.
        # Here, q is the POUND SIGN U+00A3 encoded in utf8 and then %HEX
        self.getPage("/reqparams?q=%C2%A3")
        self.assertBody(r"{'q': u'\xa3'}")
        
        # Query strings that are incorrectly encoded MUST raise 404.
        # Here, q is the POUND SIGN U+00A3 encoded in latin1 and then %HEX
        self.getPage("/reqparams?q=%A3")
        self.assertStatus(404)
        self.assertErrorPage(404, 
            "The given query string could not be processed. Query "
            "strings for this resource must be encoded with 'utf8'.")
    
    def testEncoding(self):
        # Default encoding should be utf-8
        self.getPage('/mao_zedong')
        self.assertBody(sing8)
        
        # Ask for utf-16.
        self.getPage('/mao_zedong', [('Accept-Charset', 'utf-16')])
        self.assertHeader('Content-Type', 'text/html;charset=utf-16')
        self.assertBody(sing16)
        
        # Ask for multiple encodings. ISO-8859-1 should fail, and utf-16
        # should be produced.
        self.getPage('/mao_zedong', [('Accept-Charset',
                                      'iso-8859-1;q=1, utf-16;q=0.5')])
        self.assertBody(sing16)
        
        # The "*" value should default to our default_encoding, utf-8
        self.getPage('/mao_zedong', [('Accept-Charset', '*;q=1, utf-7;q=.2')])
        self.assertBody(sing8)
        
        # Only allow iso-8859-1, which should fail and raise 406.
        self.getPage('/mao_zedong', [('Accept-Charset', 'iso-8859-1, *;q=0')])
        self.assertStatus("406 Not Acceptable")
        self.assertInBody("Your client sent this Accept-Charset header: "
                          "iso-8859-1, *;q=0. We tried these charsets: "
                          "iso-8859-1.")
        
        # Ask for x-mac-ce, which should be unknown. See ticket #569.
        self.getPage('/mao_zedong', [('Accept-Charset',
                                      'us-ascii, ISO-8859-1, x-mac-ce')])
        self.assertStatus("406 Not Acceptable")
        self.assertInBody("Your client sent this Accept-Charset header: "
                          "us-ascii, ISO-8859-1, x-mac-ce. We tried these "
                          "charsets: ISO-8859-1, us-ascii, x-mac-ce.")
        
        # Test the 'encoding' arg to encode.
        self.getPage('/utf8')
        self.assertBody(sing8)
        self.getPage('/utf8', [('Accept-Charset', 'us-ascii, ISO-8859-1')])
        self.assertStatus("406 Not Acceptable")
    
    def testGzip(self):
        zbuf = StringIO.StringIO()
        zfile = gzip.GzipFile(mode='wb', fileobj=zbuf, compresslevel=9)
        zfile.write("Hello, world")
        zfile.close()
        
        self.getPage('/gzip/', headers=[("Accept-Encoding", "gzip")])
        self.assertInBody(zbuf.getvalue()[:3])
        self.assertHeader("Vary", "Accept-Encoding")
        self.assertHeader("Content-Encoding", "gzip")
        
        # Test when gzip is denied.
        self.getPage('/gzip/', headers=[("Accept-Encoding", "identity")])
        self.assertHeader("Vary", "Accept-Encoding")
        self.assertNoHeader("Content-Encoding")
        self.assertBody("Hello, world")
        
        self.getPage('/gzip/', headers=[("Accept-Encoding", "gzip;q=0")])
        self.assertHeader("Vary", "Accept-Encoding")
        self.assertNoHeader("Content-Encoding")
        self.assertBody("Hello, world")
        
        self.getPage('/gzip/', headers=[("Accept-Encoding", "*;q=0")])
        self.assertStatus(406)
        self.assertNoHeader("Content-Encoding")
        self.assertErrorPage(406, "identity, gzip")
        
        # Test for ticket #147
        self.getPage('/gzip/noshow', headers=[("Accept-Encoding", "gzip")])
        self.assertNoHeader('Content-Encoding')
        self.assertStatus(500)
        self.assertErrorPage(500, pattern="IndexError\n")
        
        # In this case, there's nothing we can do to deliver a
        # readable page, since 1) the gzip header is already set,
        # and 2) we may have already written some of the body.
        # The fix is to never stream yields when using gzip.
        if (cherrypy.server.protocol_version == "HTTP/1.0" or
            getattr(cherrypy.server, "using_apache", False)):
            self.getPage('/gzip/noshow_stream',
                         headers=[("Accept-Encoding", "gzip")])
            self.assertHeader('Content-Encoding', 'gzip')
            self.assertInBody('\x1f\x8b\x08\x00')
        else:
            # The wsgiserver will simply stop sending data, and the HTTP client
            # will error due to an incomplete chunk-encoded stream.
            self.assertRaises((ValueError, IncompleteRead), self.getPage,
                              '/gzip/noshow_stream',
                              headers=[("Accept-Encoding", "gzip")])

if __name__ == "__main__":
    helper.testmain()
