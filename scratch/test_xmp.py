import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from downloader_app.xmp_scanner import xmp_scanner

def test_xmp_parsing():
    mock_xmp = """
    <x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 5.6-c148 79.164036, 2019/08/13-01:06:57        ">
     <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
      <rdf:Description rdf:about=""
        xmlns:xmpDM="http://ns.adobe.com/xmp/1.0/DynamicMedia/">
       <xmpDM:markers>
        <rdf:Seq>
         <rdf:li rdf:parseType="Resource">
          <xmpDM:startTime>254016000000</xmpDM:startTime>
          <xmpDM:name>Test Marker 1</xmpDM:name>
          <xmpDM:comment>First comment</xmpDM:comment>
         </rdf:li>
         <rdf:li rdf:parseType="Resource">
          <xmpDM:startTime>508032000000</xmpDM:startTime>
          <xmpDM:name>Test Marker 2</xmpDM:name>
          <xmpDM:comment>Second comment</xmpDM:comment>
         </rdf:li>
         <rdf:li rdf:parseType="Resource">
          <xmpDM:startTime>150f25</xmpDM:startTime>
          <xmpDM:name>Test Marker 3</xmpDM:name>
         </rdf:li>
        </rdf:Seq>
       </xmpDM:markers>
      </rdf:Description>
     </rdf:RDF>
    </x:xmpmeta>
    """
    
    markers = xmp_scanner.parse_markers_from_xml(mock_xmp, "test.mp4")
    
    print(f"Found {len(markers)} markers")
    for m in markers:
        print(f" - {m['name']} at {m['timeSec']}s: {m['comment']}")
    
    assert len(markers) == 3
    assert markers[0]['timeSec'] == 1.0
    assert markers[1]['timeSec'] == 2.0
    assert markers[2]['timeSec'] == 6.0 # 150 / 25
    print("Test passed!")

def test_track_marker_parsing():
    mock_xmp = """
    <x:xmpmeta xmlns:x="adobe:ns:meta/">
      <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
        <rdf:Description xmlns:xmpDM="http://ns.adobe.com/xmp/1.0/DynamicMedia/">
          <xmpDM:duration xmpDM:value="120000" xmpDM:scale="1/1000" />
          <xmpDM:Tracks>
            <rdf:Bag>
              <rdf:li rdf:parseType="Resource">
                <rdf:Description xmpDM:frameRate="f25">
                  <xmpDM:markers>
                    <rdf:Seq>
                      <rdf:li rdf:parseType="Resource">
                        <rdf:Description
                          xmpDM:startTime="150"
                          xmpDM:name="Track Marker 1"
                          xmpDM:comment="Nested description" />
                      </rdf:li>
                      <rdf:li rdf:parseType="Resource">
                        <xmpDM:startTime>300</xmpDM:startTime>
                        <xmpDM:name>Track Marker 2</xmpDM:name>
                      </rdf:li>
                    </rdf:Seq>
                  </xmpDM:markers>
                </rdf:Description>
              </rdf:li>
            </rdf:Bag>
          </xmpDM:Tracks>
        </rdf:Description>
      </rdf:RDF>
    </x:xmpmeta>
    """

    markers = xmp_scanner.parse_markers_from_xml(mock_xmp, "track_test.mp4")

    print(f"Found {len(markers)} track markers")
    for m in markers:
        print(f" - {m['name']} at {m['timeSec']}s: {m['comment']}")

    assert len(markers) == 2
    assert markers[0]["name"] == "Track Marker 1"
    assert markers[0]["timeSec"] == 6.0
    assert markers[1]["name"] == "Track Marker 2"
    assert markers[1]["timeSec"] == 12.0
    print("Track test passed!")

if __name__ == "__main__":
    test_xmp_parsing()
    test_track_marker_parsing()
