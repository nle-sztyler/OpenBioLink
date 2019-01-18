from graph_creation.Types.dbType import DbType
from graph_creation.file_reader.oboReader import OboReader
from graph_creation.Types.readerType import ReaderType
from graph_creation.metadata_db_file.onto.dbMetaOntoGo import DbMetaOntoGo
import graph_creation.globalConstant as g
import os

class OntoGoReader(OboReader):
    DB_META_CLASS = DbMetaOntoGo

    def __init__(self):
        super().__init__(
        in_path = os.path.join(g.O_FILE_PATH, self.DB_META_CLASS.OFILE_NAME),
            quadruple_list= self.DB_META_CLASS.QUADRUPLES,
            readerType= ReaderType.READER_ONTO_GO,
        dbType = DbType.DB_ONTO_GO
        )

