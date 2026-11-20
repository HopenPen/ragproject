# Назначение файла: явно синтетические text/scan/mixed PDF и typed контрольные факты.
import io
import fitz
from PIL import Image, ImageDraw
from app.schemas.graphs import SolarGraph, RagGraph, Classification


def pdf_bytes(kind='text', pages=1):
    pdf = fitz.open()
    for i in range(pages):
        page = pdf.new_page()
        text = f'SYNTHETIC Science Extract fixture. PDF page {i+1}. Voc = 1.0 V; Jsc = 20 mA/cm2; FF = 50%; PCE = 10%. RAG F1 = 0.5 fraction.'
        if kind != 'scan':
            page.insert_textbox(fitz.Rect(30,30,550,150), text, fontsize=12)
        if kind in ('scan', 'mixed'):
            image = Image.new('RGB', (1000,300), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((20,40), 'SYNTHETIC TABLE: Voc 1.0 V; PCE 10%; F1 0.5 fraction', fill='black', font_size=24)
            stream = io.BytesIO(); image.save(stream, 'PNG')
            page.insert_image(fitz.Rect(30,180,550,336), stream=stream.getvalue())
    blob = pdf.tobytes()
    pdf.close()
    return blob


def classification(labels=None, outcome='resolved', scope=True, confidence=.95):
    labels = ['solar'] if labels is None else labels
    value = {'bibliography': {'title': 'SYNTHETIC scientific fixture'}, 'labels': labels, 'outcome': outcome,
        'solar': {'in_scope': scope if 'solar' in labels else False, 'exclusion_reason': None if 'solar' in labels and scope else 'not_target_domain'},
        'rag': {'in_scope': scope if 'rag' in labels else False, 'exclusion_reason': None if 'rag' in labels and scope else 'not_target_domain'},
        'confidence': confidence,
        'evidence': [{'evidence_id':'classification-source','field_path':'labels','source_page':1,'fragment':'SYNTHETIC Science Extract fixture.', 'method':'text'}]}
    return Classification.model_validate(value).model_dump(mode='json')


def solar_graph():
    return SolarGraph.model_validate({'domain_profile':'solar-v1', 'bibliography':{'title':'SYNTHETIC solar fixture','authors':['A, Author','B Author']},
        'scope':{'in_scope':True}, 'materials':[{'material_id':'M1','material_name_raw':'perovskite','material_class':'perovskite','bandgap_value':'1.5','bandgap_unit':'eV'}],
        'devices':[{'device_id':'D1','absorber_material_id':'M1','device_type':'cell','active_area':'1.0','area_unit':'cm2','area_definition':'aperture'}],
        'measurements':[{'measurement_id':'JV1','device_id':['D1'],'measurement_type':'J-V','spectrum':'AM1.5G','light_intensity':'100','intensity_unit':'mW/cm2','scan_direction':'forward','certified':False}],
        'results':[{'result_id':'R'+str(i), 'device_id':'D1','measurement_id':'JV1','material_id':'M1','metric_name':metric,
                    'metric_value':value,'metric_unit':unit,'raw_value':value,'raw_unit':unit,'normalized_value':value,'normalized_unit':unit,
                    'result_origin':'primary','source_page':1,'source_fragment':fragment,'extraction_status':'extracted','aggregation':'champion'}
                   for i,(metric,value,unit,fragment) in enumerate([('Voc','1.0','V','Voc = 1.0 V'),('Jsc','20','mA/cm2','Jsc = 20 mA/cm2'),('FF','50','%','FF = 50%'),('PCE','10','%','PCE = 10%')],1)]}).model_dump(mode='json')


def rag_graph():
    return RagGraph.model_validate({'domain_profile':'rag-v1','bibliography':{'title':'SYNTHETIC RAG fixture'},'scope':{'in_scope':True},
        'configurations':[{'config_id':'C1','top_k':0,'generator_model':'reported-generator','embedding_model':'reported-embedding'}],
        'datasets':[{'dataset_id':'DS1','dataset_name':'SYNTHETIC','dataset_version':'1','data_split':'test'}],
        'tasks':[{'task_id':'T1','task_type':'QA'}], 'experiments':[{'experiment_id':'E1','evaluation_protocol':'exact published fixture protocol'}],
        'results':[{'result_id':'R1','experiment_id':'E1','config_id':'C1','dataset_id':'DS1','task_id':'T1', 'metric_name':'F1','metric_k':0,
                    'metric_value':'0.5','metric_unit':'fraction','raw_value':'0.5','raw_unit':'fraction','normalized_value':'0.5','normalized_unit':'fraction',
                    'result_origin':'primary','source_page':1,'source_fragment':'RAG F1 = 0.5 fraction.','extraction_status':'extracted'}]}).model_dump(mode='json')
