"""
ETF 配置加载模块
支持导入不同类别的 ETF 配置 JSON 文件
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class ETFConfigLoader:
    """ETF 配置加载器"""
    
    def __init__(self, config_dir: str = 'etf_configs'):
        """
        初始化配置加载器
        
        Args:
            config_dir: 配置文件所在目录，默认为 'etf_configs'
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
    
    def load_config(self, config_name: str) -> Dict:
        """
        加载单个配置文件
        
        Args:
            config_name: 配置文件名称（不含 .json 后缀）
            
        Returns:
            配置字典
            
        Raises:
            FileNotFoundError: 配置文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        config_path = self.config_dir / f"{config_name}.json"
        
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"JSON 格式错误: {config_path}", e.doc, e.pos)
    
    def load_multiple_configs(self, config_names: List[str]) -> Dict:
        """
        合并加载多个配置文件
        
        Args:
            config_names: 配置文件名称列表
            
        Returns:
            合并后的配置字典
        """
        merged_config = {
            'etf_list': [],
            'expense_ratio': {},
            'metadata': {}
        }
        
        for config_name in config_names:
            config = self.load_config(config_name)
            
            # 合并 ETF 列表
            if 'etf_list' in config:
                merged_config['etf_list'].extend(config['etf_list'])
            
            # 合并费用率字典
            if 'expense_ratio' in config:
                merged_config['expense_ratio'].update(config['expense_ratio'])
            
            # 合并元数据
            if 'metadata' in config:
                merged_config['metadata'][config_name] = config['metadata']
        
        return merged_config
    
    def get_etf_list(self, config: Dict) -> List[Tuple[str, str]]:
        """
        从配置获取 ETF 列表
        
        Args:
            config: 配置字典
            
        Returns:
            ETF 列表 [(ticker, name), ...]
        """
        return [tuple(etf) for etf in config.get('etf_list', [])]
    
    def get_expense_ratio_dict(self, config: Dict) -> Dict[str, float]:
        """
        从配置获取费用率字典
        
        Args:
            config: 配置字典
            
        Returns:
            费用率字典
        """
        return config.get('expense_ratio', {})
    
    def list_available_configs(self) -> List[str]:
        """
        列出所有可用的配置文件
        
        Returns:
            配置文件名称列表（不含 .json 后缀）
        """
        return [f.stem for f in self.config_dir.glob('*.json')]
    
    def validate_config(self, config: Dict) -> Tuple[bool, List[str]]:
        """
        验证配置文件的完整性
        
        Args:
            config: 配置字典
            
        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        
        # 检查必需字段
        if 'etf_list' not in config:
            errors.append("缺少 'etf_list' 字段")
        elif not isinstance(config['etf_list'], list):
            errors.append("'etf_list' 必须是列表")
        elif len(config['etf_list']) == 0:
            errors.append("'etf_list' 不能为空")
        else:
            # 验证 ETF 列表格式，支持数组或对象格式
            for i, etf in enumerate(config['etf_list']):
                # 支持 [ticker, name]、[ticker, name, type] 或 {ticker, name, ...} 对象格式
                if isinstance(etf, dict):
                    # 对象格式：检查必需的 ticker 和 name 字段
                    if 'ticker' not in etf or 'name' not in etf:
                        errors.append(f"ETF 列表项 {i} 缺少必需字段（ticker, name）")
                elif isinstance(etf, (list, tuple)):
                    # 数组格式：检查长度
                    if len(etf) < 2 or len(etf) > 3:
                        errors.append(f"ETF 列表项 {i} 格式错误，应为 [ticker, name]、[ticker, name, type] 或对象格式")
                else:
                    errors.append(f"ETF 列表项 {i} 格式错误，应为数组或对象")
        
        if 'expense_ratio' not in config:
            errors.append("缺少 'expense_ratio' 字段")
        elif not isinstance(config['expense_ratio'], dict):
            errors.append("'expense_ratio' 必须是字典")
        else:
            # 验证费用率数值
            for ticker, ratio in config['expense_ratio'].items():
                if ratio is not None and not isinstance(ratio, (int, float)):
                    errors.append(f"费用率 '{ticker}' 的值必须是数字或null，当前为 {type(ratio)}")
        
        # 检查 ETF 列表和费用率的一致性（允许null值表示数据不可用）
        if 'etf_list' in config and 'expense_ratio' in config:
            # 支持对象和数组两种格式
            tickers_in_list = []
            for etf in config['etf_list']:
                if isinstance(etf, dict):
                    tickers_in_list.append(etf.get('ticker', ''))
                else:
                    tickers_in_list.append(etf[0] if len(etf) > 0 else '')
            
            tickers_in_ratio = set(config['expense_ratio'].keys())
            
            missing_ratios = set(tickers_in_list) - tickers_in_ratio
            if missing_ratios:
                errors.append(f"以下 ETF 缺少费用率信息: {missing_ratios}")
        
        return len(errors) == 0, errors


# 便捷函数
def load_etf_config(config_name: str, config_dir: str = 'etf_configs') -> Dict:
    loader = ETFConfigLoader(config_dir)
    config = loader.load_config(config_name)
    is_valid, errors = loader.validate_config(config)
    
    if not is_valid:
        raise ValueError(f"配置验证失败:\n" + "\n".join(errors))
    
    return config


def load_multiple_etf_configs(config_names: List[str], config_dir: str = 'etf_configs') -> Dict:
    loader = ETFConfigLoader(config_dir)
    return loader.load_multiple_configs(config_names)
