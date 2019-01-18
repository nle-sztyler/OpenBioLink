from graph_creation.file_reader.fileReader import FileReader
from graph_creation.file_reader.parser.postgresDumpParser import PostgresDumpParser as dcp

class SqlReader(FileReader):

    def __init__(self, in_path, table_name, cols, readerType, dbType):
        super().__init__(in_path, readerType, dbType)
        self.table_name = table_name
        self.cols= cols

    def read_file(self):
        file = FileReader.open_file(self.in_path)
        df = dcp.table_to_df(file, self.table_name, self.cols)
        return df
